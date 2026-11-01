"""delivery.py - deliver the finished digest.

Backend chosen by env DIGEST_DELIVERY (local|email). "local" is the default:
print to stdout and write dated files under digests/. "email" additionally
sends via Gmail SMTP, using stdlib only.
"""
import html
import json
import os
import smtplib
import sys
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def deliver(markdown: str, stories: list[dict]) -> None:
    """Deliver the rendered digest and its stories."""
    backend = os.environ.get("DIGEST_DELIVERY", "local")
    if backend == "local":
        _deliver_local(markdown, stories)
        return
    if backend == "email":
        _deliver_email(markdown, stories)
        return
    raise NotImplementedError(f"Unknown DIGEST_DELIVERY backend '{backend}'.")


def _save_files(markdown: str, stories: list[dict]) -> tuple[Path, Path, Path, str]:
    """Write the .md/.json/.html files under digests/. Returns their paths
    and the rendered HTML, so a failed send still leaves the files in place."""
    out_dir = Path("digests")
    out_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    md_path = out_dir / f"{timestamp}.md"
    json_path = out_dir / f"{timestamp}.json"
    html_path = out_dir / f"{timestamp}.html"

    html_content = render_html(stories)

    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(stories, indent=2, ensure_ascii=False), encoding="utf-8")
    html_path.write_text(html_content, encoding="utf-8")

    return md_path, json_path, html_path, html_content


def _deliver_local(markdown: str, stories: list[dict]) -> None:
    print(markdown)

    md_path, json_path, html_path, _ = _save_files(markdown, stories)
    print(f"\n[saved] {md_path}")
    print(f"[saved] {json_path}")
    print(f"[saved] {html_path}")


def _deliver_email(markdown: str, stories: list[dict]) -> None:
    if not stories:
        print("No new stories, email skipped")
        return

    md_path, json_path, html_path, html_content = _save_files(markdown, stories)
    print(f"[saved] {md_path}")
    print(f"[saved] {json_path}")
    print(f"[saved] {html_path}")

    text = render_text(stories)
    subject = f"Daily digest {date.today().isoformat()}: {len(stories)} stories"
    msg = build_message(subject, text, html_content)
    send(msg)  # already saved above, so a failed send loses nothing
    print("[sent] digest emailed")


def safe_url(url: str) -> str:
    """Return the url if it's http(s), else a harmless placeholder."""
    if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
        return url
    return "#"


def render_html(stories: list[dict]) -> str:
    """Render the digest as inline-styled HTML, grouped by topic in story order."""
    topic_order = list(dict.fromkeys(s.get("topic", "") for s in stories))
    by_topic: dict[str, list[dict]] = {}
    for s in stories:
        by_topic.setdefault(s.get("topic", ""), []).append(s)

    body = []
    for topic in topic_order:
        body.append(
            f'<h2 style="font-size:18px;margin:24px 0 8px;color:#111827;">'
            f'{html.escape(str(topic))}</h2>'
        )
        for story in by_topic[topic]:
            headline = html.escape(str(story.get("headline", "")))
            summary = html.escape(str(story.get("summary", "")))
            href = html.escape(safe_url(story.get("url", "")), quote=True)

            body.append(
                f'<h3 style="font-size:16px;margin:16px 0 4px;">'
                f'<a href="{href}" style="color:#1a56db;text-decoration:none;">{headline}</a>'
                f'</h3>'
            )

            snippet_note = ""
            if story.get("basis") == "snippet":
                snippet_note = (
                    ' <span style="color:#6b7280;font-size:12px;">'
                    '(based on a search snippet only)</span>'
                )
            body.append(
                f'<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.5;">'
                f'{summary}{snippet_note}</p>'
            )

    return (
        '<div style="max-width:600px;margin:0 auto;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;'
        'color:#111827;">'
        + "".join(body) +
        "</div>"
    )


def render_text(stories: list[dict]) -> str:
    """Render the digest as plain text, grouped by topic in story order."""
    topic_order = list(dict.fromkeys(s.get("topic", "") for s in stories))
    by_topic: dict[str, list[dict]] = {}
    for s in stories:
        by_topic.setdefault(s.get("topic", ""), []).append(s)

    lines = []
    for topic in topic_order:
        lines.append(str(topic))
        lines.append("=" * len(str(topic)))
        for story in by_topic[topic]:
            lines.append(str(story.get("headline", "")))
            lines.append(str(story.get("summary", "")))
            lines.append(str(story.get("url", "")))
            lines.append("")

    return "\n".join(lines)


def build_message(subject: str, text: str, html_content: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("GMAIL_USER")
    msg["To"] = os.environ.get("DIGEST_TO")
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
