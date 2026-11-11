"""images.py - find a representative image for an article URL.

Pure code, no LLM calls. Runs as a batch enrichment pass over already-chosen
stories (see enrich_images). Every public entry point fails closed: network
errors, parsing errors, and anything that looks like it could be an SSRF
vector all just result in a None image rather than a raised exception.
"""
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; AgenticNewsletterBot/1.0)"
TIMEOUT = 8.0
MAX_BODY_BYTES = 300_000
MAX_REDIRECTS = 3

MIN_IMAGE_WIDTH = 400
MIN_IMAGE_BYTES = 8 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024

_BAD_PATH_SUBSTRINGS = (
    "logo", "favicon", "icon", "sprite", "placeholder",
    "default", "avatar", "blank", "pixel",
)
_BAD_EXTENSIONS = (".svg", ".gif")

_META_IMAGE_CANDIDATES = (
    ("meta", {"property": "og:image:secure_url"}, "content"),
    ("meta", {"property": "og:image"}, "content"),
    ("meta", {"name": "twitter:image"}, "content"),
    ("link", {"rel": "image_src"}, "href"),
)


class _Response:
    """Minimal response shape expected from a `fetch` callable:
    status_code (int), headers (dict-like), text (str, GET only), url (str)."""
    __slots__ = ("status_code", "headers", "text", "url")

    def __init__(self, status_code, headers, text, url):
        self.status_code = status_code
        self.headers = headers
        self.text = text
        self.url = url


def _default_fetch(method, url, headers, timeout):
    """Real network fetch via httpx. Raises on transport errors; callers
    catch broadly around this. Redirects are NOT followed here - the
    caller walks hops itself so it can SSRF-check each one."""
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        if method == "GET":
            with client.stream(method, url, headers=headers) as resp:
                body = b""
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) >= MAX_BODY_BYTES:
                        break
                text = body.decode(resp.encoding or "utf-8", errors="replace")
                return _Response(resp.status_code, dict(resp.headers), text, str(resp.url))
        else:
            resp = client.request(method, url, headers=headers)
            return _Response(resp.status_code, dict(resp.headers), "", str(resp.url))


def _header_get(headers, name):
    """Case-insensitive header lookup that tolerates plain dicts, not just
    httpx.Headers, since test doubles will usually hand us a plain dict."""
    if not headers:
        return None
    name_lower = name.lower()
    try:
        items = headers.items()
    except AttributeError:
        return None
    for key, value in items:
        if key.lower() == name_lower:
            return value
    return None


def _is_safe_url(url):
    """SSRF guard. Scheme must be http/https; a bare IP literal or a name
    like 'localhost' is rejected outright; otherwise every address the host
    resolves to (via getaddrinfo) must be public. DNS failures fail closed."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.hostname
    if not host:
        return False

    if host.lower() == "localhost":
        return False

    try:
        ipaddress.ip_address(host)
        return False  # bare IP literal in the URL - reject immediately
    except ValueError:
        pass  # not a literal IP; fall through to DNS resolution below

    try:
        addrs = socket.getaddrinfo(host, None)
    except OSError:
        return False  # DNS failure -> fail closed

    for addr in addrs:
        sockaddr = addr[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        # is_global is the real test: not just private/loopback/link-local/
        # reserved/multicast, but also ranges those miss individually (e.g.
        # 100.64.0.0/10 CGNAT space - is_private, is_reserved etc. are all
        # False for it, but it's still not a public, globally-routable
        # address, and is the default overlay range for tools like Tailscale).
        if not ip.is_global:
            return False

    return True


def _fetch_page(page_url, fetch):
    """Follow redirects manually (up to MAX_REDIRECTS hops), SSRF-checking
    every hop, and return (response, final_url) for the final text/html
    response - or None on any failure."""
    current = page_url
    for _ in range(MAX_REDIRECTS + 1):
        if not _is_safe_url(current):
            return None
        try:
            resp = fetch("GET", current, {"User-Agent": USER_AGENT}, TIMEOUT)
        except Exception:
            return None

        status = getattr(resp, "status_code", None)
        if status in (301, 302, 303, 307, 308):
            location = _header_get(resp.headers, "location")
            if not location:
                return None
            current = urljoin(current, location)
            continue

        content_type = (_header_get(resp.headers, "content-type") or "").lower()
        if not content_type.startswith("text/html"):
            return None
        return resp, current

    return None  # too many redirect hops


def _find_og_width(soup):
    tag = soup.find("meta", attrs={"property": "og:image:width"})
    if not tag or not tag.get("content"):
        return None
    try:
        return int(str(tag["content"]).strip())
    except ValueError:
        return None


def _extract_image_candidate(html_text, final_url):
    """Return (image_url, width_or_None), or (None, None) if nothing found."""
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        return None, None

    for tag_name, attrs, attr_key in _META_IMAGE_CANDIDATES:
        tag = soup.find(tag_name, attrs=attrs)
        value = tag.get(attr_key) if tag else None
        if value and str(value).strip():
            width = _find_og_width(soup)
            return urljoin(final_url, str(value).strip()), width

    return None, None


def _looks_like_bad_image_path(path_lower):
    if path_lower.endswith(_BAD_EXTENSIONS):
        return True
    return any(bad in path_lower for bad in _BAD_PATH_SUBSTRINGS)


def _head_check_ok(image_url, fetch):
    """True if a HEAD request either confirms the image is plausible, or
    was inconclusive (failed, errored, or missing the info we need) - a
    flaky HEAD should never be the reason a good image gets rejected."""
    try:
        resp = fetch("HEAD", image_url, {"User-Agent": USER_AGENT}, TIMEOUT)
    except Exception:
        return True

    status = getattr(resp, "status_code", None)
    if status is None or status >= 400:
        return True  # HEAD failed outright -> inconclusive, accept

    content_type = _header_get(resp.headers, "content-type")
    if content_type and not content_type.lower().startswith("image/"):
        return False

    content_length = _header_get(resp.headers, "content-length")
    if content_length is not None:
        try:
            length = int(content_length)
        except (TypeError, ValueError):
            length = None
        if length is not None and (length < MIN_IMAGE_BYTES or length > MAX_IMAGE_BYTES):
            return False

    return True


def _validate_image_url(image_url, width, fetch):
    if not image_url or image_url.lower().startswith("data:"):
        return None

    try:
        parsed = urlparse(image_url)
    except Exception:
        return None

    if parsed.scheme != "https":
        return None

    if _looks_like_bad_image_path(parsed.path.lower()):
        return None

    if width is not None and width < MIN_IMAGE_WIDTH:
        return None

    if not _is_safe_url(image_url):
        return None

    if not _head_check_ok(image_url, fetch):
        return None

    return image_url


def find_image(page_url, fetch=None):
    """Find a representative image URL for an article page. Never raises -
    any failure (network, parsing, validation) returns None. `fetch` is an
    injectable callable so tests can run with no network access.

    fetch(method, url, headers, timeout) -> object with .status_code,
    .headers (dict-like), .text (GET body), .url - matching _Response.
    """
    try:
        active_fetch = fetch or _default_fetch
        fetched = _fetch_page(page_url, active_fetch)
        if fetched is None:
            return None
        resp, final_url = fetched

        image_url, width = _extract_image_candidate(resp.text, final_url)
        if not image_url:
            return None

        return _validate_image_url(image_url, width, active_fetch)
    except Exception:
        return None


def _resolve_one(story, fetch):
    """Never raises - find_image already fails closed, but a malformed
    story dict (e.g. missing "url") must not take down the whole pool."""
    try:
        return find_image(story.get("url"), fetch=fetch)
    except Exception:
        return None


def enrich_images(stories, budget_seconds=25, workers=5):
    """Set story["image_url"] (str or None) on every story in place, using
    a thread pool. One story's failure must never affect another's result.
    Stops waiting once budget_seconds has elapsed (stories not yet resolved
    by then get image_url=None). Prints "[images] N of M stories have an
    image" when done."""
    m = len(stories)

    executor = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        future_to_story = {
            executor.submit(_resolve_one, story, None): story for story in stories
        }
        done, not_done = wait(future_to_story.keys(), timeout=budget_seconds)

        for future in done:
            story = future_to_story[future]
            try:
                story["image_url"] = future.result()
            except Exception:
                story["image_url"] = None

        for future in not_done:
            story = future_to_story[future]
            story["image_url"] = None
            future.cancel()
    finally:
        # Don't block the budget on stragglers finishing in the background.
        executor.shutdown(wait=False)

    # Duplicate pass: a shared publisher default/share image should not be
    # attributed to multiple stories as if it were representative of each.
    by_url = {}
    for story in stories:
        url = story.get("image_url")
        if url:
            by_url.setdefault(url, []).append(story)

    for url, dup_stories in by_url.items():
        if len(dup_stories) >= 2:
            for story in dup_stories:
                story["image_url"] = None

    n = sum(1 for story in stories if story.get("image_url"))
    print(f"[images] {n} of {m} stories have an image")
