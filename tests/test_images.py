"""tests/test_images.py - unit tests for images.py. No network access
required: all HTTP is replaced with injected fake `fetch` callables, and
DNS resolution is replaced with a fake socket.getaddrinfo table.

Run with: python tests/test_images.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # project root, for `import images`

import socket
import time
import unittest
from unittest import mock

import images

# A small fake DNS table so _is_safe_url's getaddrinfo() call never touches
# the real network. Every hostname used by a test (other than the
# deliberately-dangerous IP-literal/localhost cases, which are rejected
# before DNS is even consulted) must be listed here.
_FAKE_DNS = {
    "example.com": "93.184.216.34",
    "cdn.example.com": "93.184.216.35",
    "img.example.com": "93.184.216.36",
    "rebind.example.com": "127.0.0.1",  # DNS-rebinding case: safe-looking name, dangerous IP
    "cgnat.example.com": "100.64.0.1",  # RFC 6598 shared/CGNAT space - not private/reserved/
                                        # loopback/link-local/multicast individually, but not
                                        # globally routable either (also Tailscale's default range)
}


def _fake_getaddrinfo(host, port, *args, **kwargs):
    ip = _FAKE_DNS.get(host)
    if ip is None:
        raise socket.gaierror(f"no fake DNS entry for {host!r}")
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]


class FakeResponse:
    def __init__(self, status_code, headers, text="", url=""):
        self.status_code = status_code
        self.headers = headers
        self.text = text
        self.url = url


def _html(image_tag, extra=""):
    return f"<html><head>{image_tag}{extra}</head><body></body></html>"


class ImagesTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("images.socket.getaddrinfo", _fake_getaddrinfo)
        patcher.start()
        self.addCleanup(patcher.stop)


def _never_called(method, url, headers, timeout):
    raise AssertionError(f"fetch should not have been called for {method} {url}")


def _ok_head(content_type="image/jpeg", content_length=50_000):
    def head(method, url, headers, timeout):
        return FakeResponse(200, {"content-type": content_type, "content-length": str(content_length)}, "", url)
    return head


class TestOgImageRelative(ImagesTestCase):
    def test_relative_og_image_resolves_against_final_url(self):
        page_html = _html('<meta property="og:image" content="/img/photo.jpg">')

        def fetch(method, url, headers, timeout):
            if method == "GET":
                return FakeResponse(200, {"content-type": "text/html; charset=utf-8"}, page_html, url)
            if method == "HEAD":
                return FakeResponse(200, {"content-type": "image/jpeg", "content-length": "50000"}, "", url)
            raise AssertionError("unexpected method")

        result = images.find_image("https://example.com/article", fetch=fetch)
        self.assertEqual(result, "https://example.com/img/photo.jpg")


class TestTwitterImageFallback(ImagesTestCase):
    def test_twitter_image_used_when_no_og_image(self):
        page_html = _html('<meta name="twitter:image" content="https://cdn.example.com/pic.jpg">')

        def fetch(method, url, headers, timeout):
            if method == "GET":
                return FakeResponse(200, {"content-type": "text/html"}, page_html, url)
            if method == "HEAD":
                return FakeResponse(200, {"content-type": "image/png", "content-length": "100000"}, "", url)
            raise AssertionError("unexpected method")

        result = images.find_image("https://example.com/article", fetch=fetch)
        self.assertEqual(result, "https://cdn.example.com/pic.jpg")


class TestRejectedCandidates(ImagesTestCase):
    def _run(self, image_content, extra=""):
        page_html = _html(f'<meta property="og:image" content="{image_content}">', extra)

        def fetch(method, url, headers, timeout):
            if method == "GET":
                return FakeResponse(200, {"content-type": "text/html"}, page_html, url)
            raise AssertionError("HEAD should never be reached for a pre-rejected candidate")

        return images.find_image("https://example.com/article", fetch=fetch)

    def test_logo_in_path_rejected(self):
        self.assertIsNone(self._run("https://cdn.example.com/assets/logo.jpg"))

    def test_favicon_in_path_rejected(self):
        self.assertIsNone(self._run("https://cdn.example.com/favicon.jpg"))

    def test_svg_extension_rejected(self):
        self.assertIsNone(self._run("https://cdn.example.com/photo.svg"))

    def test_gif_extension_rejected(self):
        self.assertIsNone(self._run("https://cdn.example.com/photo.gif"))

    def test_data_uri_rejected(self):
        self.assertIsNone(self._run("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA"))

    def test_narrow_width_rejected(self):
        self.assertIsNone(self._run(
            "https://cdn.example.com/photo.jpg",
            extra='<meta property="og:image:width" content="200">',
        ))

    def test_http_image_url_rejected(self):
        # The page itself may be fetched over http, but the *image* URL
        # must be https-only regardless of the page's own scheme.
        self.assertIsNone(self._run("http://cdn.example.com/photo.jpg"))


class TestSSRFGuard(ImagesTestCase):
    DANGEROUS_PAGE_URLS = [
        "http://169.254.169.254/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://[::1]/",
        "http://localhost/",
    ]

    def test_dangerous_initial_urls_rejected_without_fetching(self):
        for url in self.DANGEROUS_PAGE_URLS:
            with self.subTest(url=url):
                self.assertIsNone(images.find_image(url, fetch=_never_called))

    def test_dangerous_redirect_target_rejected(self):
        # The initial URL is safe; the server then redirects to a
        # metadata-endpoint-style address. The loop must re-check safety
        # on every hop, not just the first.
        calls = {"count": 0}

        def fetch(method, url, headers, timeout):
            calls["count"] += 1
            if url == "https://example.com/start":
                return FakeResponse(302, {"location": "http://169.254.169.254/latest/meta-data/"}, "", url)
            raise AssertionError(f"should never follow the redirect to {url}")

        result = images.find_image("https://example.com/start", fetch=fetch)
        self.assertIsNone(result)
        self.assertEqual(calls["count"], 1)

    def test_dns_rebinding_to_loopback_rejected(self):
        # A hostname that looks fine but resolves (per our fake DNS table)
        # to 127.0.0.1 must be rejected too - the guard is address-based,
        # not just literal-string-based.
        result = images.find_image("http://rebind.example.com/", fetch=_never_called)
        self.assertIsNone(result)

    def test_cgnat_range_rejected(self):
        # 100.64.0.0/10 is not private/reserved/loopback/link-local/
        # multicast per Python's ipaddress flags individually, but it's
        # still not globally routable (and is Tailscale's default overlay
        # range) - the guard must catch it via is_global, not just the
        # five specific flags.
        result = images.find_image("http://cgnat.example.com/", fetch=_never_called)
        self.assertIsNone(result)


class TestEnrichImagesDeduplication(unittest.TestCase):
    def test_duplicate_image_url_nulled_on_both_stories(self):
        shared = "https://img.example.com/shared.jpg"
        unique = "https://img.example.com/unique.jpg"
        resolved = {
            "https://a.example/1": shared,
            "https://a.example/2": shared,
            "https://a.example/3": unique,
        }

        def fake_find_image(url, fetch=None):
            return resolved.get(url)

        stories = [{"url": u} for u in resolved]

        with mock.patch("images.find_image", side_effect=fake_find_image):
            images.enrich_images(stories, budget_seconds=5, workers=3)

        by_url = {s["url"]: s["image_url"] for s in stories}
        self.assertIsNone(by_url["https://a.example/1"])
        self.assertIsNone(by_url["https://a.example/2"])
        self.assertEqual(by_url["https://a.example/3"], unique)

    def test_budget_timeout_does_not_block_on_slow_story(self):
        def fake_find_image(url, fetch=None):
            if url == "https://a.example/slow":
                time.sleep(0.6)
                return "https://img.example.com/slow.jpg"
            return "https://img.example.com/fast.jpg"

        stories = [{"url": "https://a.example/slow"}, {"url": "https://a.example/fast"}]

        with mock.patch("images.find_image", side_effect=fake_find_image):
            start = time.monotonic()
            images.enrich_images(stories, budget_seconds=0.1, workers=2)
            elapsed = time.monotonic() - start

        self.assertLess(elapsed, 0.5)
        by_url = {s["url"]: s["image_url"] for s in stories}
        self.assertIsNone(by_url["https://a.example/slow"])
        self.assertEqual(by_url["https://a.example/fast"], "https://img.example.com/fast.jpg")


class TestFetchExceptionIsSwallowed(ImagesTestCase):
    def test_fetch_raising_returns_none(self):
        def fetch(method, url, headers, timeout):
            raise RuntimeError("simulated network failure")

        result = images.find_image("https://example.com/article", fetch=fetch)
        self.assertIsNone(result)


class TestHeadCheckLeniency(ImagesTestCase):
    def test_head_failure_does_not_block_otherwise_valid_image(self):
        page_html = _html('<meta property="og:image" content="https://cdn.example.com/photo.jpg">')

        def fetch(method, url, headers, timeout):
            if method == "GET":
                return FakeResponse(200, {"content-type": "text/html"}, page_html, url)
            if method == "HEAD":
                raise RuntimeError("HEAD endpoint flaky")
            raise AssertionError("unexpected method")

        result = images.find_image("https://example.com/article", fetch=fetch)
        self.assertEqual(result, "https://cdn.example.com/photo.jpg")

    def test_head_wrong_content_type_rejected(self):
        page_html = _html('<meta property="og:image" content="https://cdn.example.com/photo.jpg">')

        def fetch(method, url, headers, timeout):
            if method == "GET":
                return FakeResponse(200, {"content-type": "text/html"}, page_html, url)
            if method == "HEAD":
                return FakeResponse(200, {"content-type": "text/html"}, "", url)
            raise AssertionError("unexpected method")

        result = images.find_image("https://example.com/article", fetch=fetch)
        self.assertIsNone(result)

    def test_head_too_small_content_length_rejected(self):
        page_html = _html('<meta property="og:image" content="https://cdn.example.com/photo.jpg">')

        def fetch(method, url, headers, timeout):
            if method == "GET":
                return FakeResponse(200, {"content-type": "text/html"}, page_html, url)
            if method == "HEAD":
                return FakeResponse(200, {"content-type": "image/jpeg", "content-length": "500"}, "", url)
            raise AssertionError("unexpected method")

        result = images.find_image("https://example.com/article", fetch=fetch)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
