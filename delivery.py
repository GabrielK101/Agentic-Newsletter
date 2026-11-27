"""delivery.py - deliver the finished digest.

Backend chosen by env DIGEST_DELIVERY (local|email). "local" is the default:
print to stdout and write dated files under digests/ (including a
webpage.py web edition, alongside the email-style .md/.json/.html). "email"
additionally sends via Gmail SMTP, using stdlib only.

The email itself defaults to email_render.render_email_html - the mobile-
first, single-column-by-default layout (see that module). Set
DIGEST_EMAIL_MODE=teaser to send the older short teaser instead (masthead,
lead headline + dek, secondary headlines, a button to the web edition) -
see newsletter_render.render_teaser_html. Either way, when DIGEST_WEB_BUCKET
is set the web edition is published (storage.publish_public_edition)
BEFORE the email is built, and its public url is linked in the email; if
publishing isn't configured or fails, the email still sends, just without
that link - a failed publish must never block delivery.
"""
import json
import os
import smtplib
import sys
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

import storage
from email_render import render_email_html, render_email_text
from newsletter_render import render_html, render_teaser_html, render_teaser_text, render_text
from webpage import render_web

load_dotenv()

_SUBJECT_MAX_CHARS = 78


def deliver(markdown: str, stories: list[dict], title: str = "The Daily Digest",
            tagline: str | None = None, recipient: str | None = None,
            front_page: dict | None = None) -> None:
    """Deliver the rendered digest and its stories. `recipient` (email
    backend only) falls back to env DIGEST_TO if not given. `front_page`
    is the same already-filtered front-page shape passed to the email
    layout - when given, a web edition is also written to digests/
    alongside the usual .md/.json/.html files, and (email backend only)
    is what the email itself is built from."""
    backend = os.environ.get("DIGEST_DELIVERY", "local")
    if backend == "local":
        _deliver_local(markdown, stories, title, tagline, front_page)
        return
    if backend == "email":
        _deliver_email(markdown, stories, title, tagline, recipient, front_page)
        return
    raise NotImplementedError(f"Unknown DIGEST_DELIVERY backend '{backend}'.")


def _unique_stem(out_dir: Path, base: str) -> str:
    """`base`, or `base_2`/`base_3`/... if any of .md/.json/.html already
    exist for it - guards against two runs landing in the same second."""
    stem = base
    n = 1
    while any((out_dir / f"{stem}{ext}").exists() for ext in (".md", ".json", ".html")):
        n += 1
        stem = f"{base}_{n}"
    return stem


def _save_files(markdown: str, stories: list[dict], title: str, tagline: str | None,
                 front_page: dict | None = None) -> tuple[Path, Path, Path, str, Path | None, str | None]:
    """Write the .md/.json/.html files under digests/, plus a .web.html
    web edition (same stem) when `front_page` is given. Returns their
    paths, the rendered archival email HTML, the web path, and the web
    edition's own HTML (so a caller publishing it publicly doesn't have
    to re-render it) - a failed send still leaves the files in place."""
    out_dir = Path("digests")
    out_dir.mkdir(exist_ok=True)
    stem = _unique_stem(out_dir, datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"
    html_path = out_dir / f"{stem}.html"

    html_content = render_html(stories, title=title, tagline=tagline)

    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(stories, indent=2, ensure_ascii=False), encoding="utf-8")
    html_path.write_text(html_content, encoding="utf-8")

    web_path = None
    web_html = None
    if front_page is not None:
        web_path = out_dir / f"{stem}.web.html"
        web_html = render_web(front_page, title=title, tagline=tagline)
        web_path.write_text(web_html, encoding="utf-8")
        storage.upload_web(web_path.name, web_html)  # no-op unless gcs + DIGEST_ARCHIVE=true

    return md_path, json_path, html_path, html_content, web_path, web_html


def _deliver_local(markdown: str, stories: list[dict], title: str, tagline: str | None,
                    front_page: dict | None = None) -> None:
    print(markdown)

    md_path, json_path, html_path, _, web_path, _ = _save_files(markdown, stories, title, tagline, front_page)
    print(f"\n[saved] {md_path}")
    print(f"[saved] {json_path}")
    print(f"[saved] {html_path}")
    if web_path is not None:
        print(f"[saved] {web_path}")


def _truncate_subject(text: str, max_chars: int = _SUBJECT_MAX_CHARS) -> str:
    """`text` cut to at most `max_chars`, at a word boundary (never
    mid-word), with an ellipsis if it was cut."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated.rstrip() + "…"


def _build_subject(lead: dict | None, title: str, date_str: str) -> str:
    """"<lead headline> · <date>", truncated at a word boundary to
    _SUBJECT_MAX_CHARS - or "<title> · <date>" when there's no lead."""
    base = lead["headline"] if lead and lead.get("headline") else title
    subject = f"{base} · {date_str}"
    return _truncate_subject(subject)


def _deliver_email(markdown: str, stories: list[dict], title: str, tagline: str | None,
                    recipient: str | None, front_page: dict | None = None) -> None:
    if not stories:
        print("No new stories, email skipped")
        return

    md_path, json_path, html_path, html_content, web_path, web_html = _save_files(
        markdown, stories, title, tagline, front_page,
    )
    print(f"[saved] {md_path}")
    print(f"[saved] {json_path}")
    print(f"[saved] {html_path}")
    if web_path is not None:
        print(f"[saved] {web_path}")

    to_addr = recipient or os.environ.get("DIGEST_TO")
    date_str = date.today().strftime("%a %d %b")

    # Publish the web edition to the PUBLIC bucket (if DIGEST_WEB_BUCKET is
    # set) before building the email, so the email can link to it. A
    # missing config or a failed publish both just mean no link - they
    # must never block the email itself.
    web_url = None
    if web_html is not None and front_page is not None:
        web_url = storage.publish_public_edition(
            web_html, date.today().isoformat(),
            recipient=to_addr, notes=str(front_page.get("notes") or ""),
        )

    mode = os.environ.get("DIGEST_EMAIL_MODE", "full")
    lead = (front_page or {}).get("lead")

    if mode == "teaser" and front_page is not None:
        text = render_teaser_text(front_page, title, web_url or "")
        email_html = render_teaser_html(front_page, title, tagline, web_url or "")
    elif front_page is not None:
        text = render_email_text(front_page, title, web_url, date_str)
        email_html = render_email_html(front_page, title, tagline, web_url, date_str)
    else:
        # No structured front_page - fall back to the old flat-stories
        # layout rather than failing; should not happen in practice.
        text = render_text(stories)
        email_html = html_content

    subject = _build_subject(lead, title, date_str)
    msg = build_message(subject, text, email_html, to_addr)
    send(msg)  # already saved above, so a failed send loses nothing
    print("[sent] digest emailed")


def build_message(subject: str, text: str, html_content: str, to_addr: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("GMAIL_USER")
    msg["To"] = to_addr or os.environ.get("DIGEST_TO")
    msg.set_content(text)
    msg.add_alternative(html_content, subtype="html")
    return msg


def send(msg: EmailMessage) -> None:
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(gmail_user, gmail_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        print("[error] email login failed - check GMAIL_USER and GMAIL_APP_PASSWORD.")
        sys.exit(1)
    except (smtplib.SMTPException, OSError) as e:
        print(f"[error] failed to send email: {type(e).__name__}: {e}")
        sys.exit(1)
