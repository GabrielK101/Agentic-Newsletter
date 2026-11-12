"""delivery.py - deliver the finished digest.

Backend chosen by env DIGEST_DELIVERY (local|email). "local" is the default:
print to stdout and write dated files under digests/ (including a
webpage.py web edition, alongside the email-style .md/.json/.html). "email"
additionally sends via Gmail SMTP, using stdlib only.

The email HTML side is ONE adaptive front-page layout, not a choice of
styles: masthead -> hero -> a grid of up to MAX_CARDS-1 cards (weight-3
stories first, then weight-2, packed into rows of 3 that never leave a
lone card) -> a 2-column brief list for everything else -> a footer. Every
band is a full-width table so columns inside it always end together, and a
thin rule separates each major section. The model never chooses layout -
it only supplies "lead" and "weight"; everything else here is deterministic.

If env DIGEST_WEB_BASE_URL is set, the email backend sends a short teaser
instead (masthead, lead headline + dek, secondary headlines, a button to
the web edition) rather than the full layout - see render_teaser_html in
newsletter_render.py.
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
from newsletter_render import render_html, render_teaser_html, render_teaser_text, render_text
from webpage import render_web

load_dotenv()


def deliver(markdown: str, stories: list[dict], title: str = "The Daily Digest",
            tagline: str | None = None, recipient: str | None = None,
            front_page: dict | None = None) -> None:
    """Deliver the rendered digest and its stories. `recipient` (email
    backend only) falls back to env DIGEST_TO if not given. `front_page`
    is the same already-filtered front-page shape passed to the email
    layout - when given, a web edition is also written to digests/
    alongside the usual .md/.json/.html files (and, email backend only,
    used for a teaser email instead of the full layout when
    DIGEST_WEB_BASE_URL is set - see _deliver_email)."""
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
                 front_page: dict | None = None) -> tuple[Path, Path, Path, str, Path | None]:
    """Write the .md/.json/.html files under digests/, plus a .web.html
    web edition (same stem) when `front_page` is given. Returns their
    paths and the rendered email HTML, so a failed send still leaves the
    files in place."""
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
    if front_page is not None:
        web_path = out_dir / f"{stem}.web.html"
        web_html = render_web(front_page, title=title, tagline=tagline)
        web_path.write_text(web_html, encoding="utf-8")
        storage.upload_web(web_path.name, web_html)  # no-op unless gcs + DIGEST_ARCHIVE=true

    return md_path, json_path, html_path, html_content, web_path


def _deliver_local(markdown: str, stories: list[dict], title: str, tagline: str | None,
                    front_page: dict | None = None) -> None:
    print(markdown)

    md_path, json_path, html_path, _, web_path = _save_files(markdown, stories, title, tagline, front_page)
    print(f"\n[saved] {md_path}")
    print(f"[saved] {json_path}")
    print(f"[saved] {html_path}")
    if web_path is not None:
        print(f"[saved] {web_path}")


def _deliver_email(markdown: str, stories: list[dict], title: str, tagline: str | None,
                    recipient: str | None, front_page: dict | None = None) -> None:
    if not stories:
        print("No new stories, email skipped")
        return

    # DIGEST_WEB_BASE_URL set -> a short teaser email linking to the web
    # edition, instead of the full layout rendered inline. Unset -> the
    # full email, unchanged, exactly as before this existed.
    web_base_url = os.environ.get("DIGEST_WEB_BASE_URL")
    use_teaser = bool(web_base_url) and front_page is not None

    md_path, json_path, html_path, html_content, web_path = _save_files(
        markdown, stories, title, tagline, front_page if use_teaser else None,
    )
    print(f"[saved] {md_path}")
    print(f"[saved] {json_path}")
    print(f"[saved] {html_path}")
    if web_path is not None:
        print(f"[saved] {web_path}")

    if use_teaser and web_path is not None:
        web_url = f"{web_base_url.rstrip('/')}/{web_path.name}"
        text = render_teaser_text(front_page, title, web_url)
        email_html = render_teaser_html(front_page, title, tagline, web_url)
        subject = f"Daily digest {date.today().isoformat()}: today's front page"
    else:
        text = render_text(stories)
        email_html = html_content
        subject = f"Daily digest {date.today().isoformat()}: {len(stories)} stories"

    to_addr = recipient or os.environ.get("DIGEST_TO")
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
