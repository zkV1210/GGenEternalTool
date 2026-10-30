"""Bounded, identifiable requests for a future reviewed network importer.

No source or image URL is enabled by default. robots.txt is an additional check,
not evidence of permission to download or redistribute content.
"""

import math
import random
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from gget_scanner.catalog.models import CatalogError

USER_AGENT = "GGETCatalogImporter/0.1"


class FetchFailed(CatalogError):
    """Temporary network failures exhausted the retry budget."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Fetcher:
    def __init__(self, *, allowed_urls=(), min_delay=8.0, max_delay=15.0,
                 timeout=20.0, retries=2, opener=None, sleep=time.sleep,
                 monotonic=time.monotonic, uniform=random.uniform):
        if (any(type(v) not in (int, float) or not math.isfinite(v)
                for v in (min_delay, max_delay, timeout)) or
                not 1 <= min_delay <= max_delay or timeout <= 0 or
                type(retries) is not int or not 0 <= retries <= 2):
            raise CatalogError("HTTP: delays must be finite, 1 <= min <= max; timeout > 0; retries 0..2")
        self.allowed_urls = frozenset(allowed_urls)
        for url in self.allowed_urls:
            parts = urlsplit(url)
            if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                    or parts.fragment or parts.port not in (None, 443)):
                raise CatalogError("HTTP: only reviewed HTTPS URLs without credentials/fragments")
        self.min_delay, self.max_delay, self.timeout, self.retries = min_delay, max_delay, timeout, retries
        self.opener = opener or build_opener(_NoRedirect()).open
        self.sleep, self.monotonic, self.uniform = sleep, monotonic, uniform
        self.last_finished = None
        self.robots = {}

    def _request(self, url, max_bytes):
        for attempt in range(self.retries + 1):
            if self.last_finished is not None:
                delay = self.uniform(self.min_delay, self.max_delay)
                self.sleep(max(0.0, delay - (self.monotonic() - self.last_finished)))
            try:
                request = Request(url, headers={"User-Agent": USER_AGENT})
                with self.opener(request, timeout=self.timeout) as response:
                    if response.geturl() != url or response.status != 200:
                        raise CatalogError("HTTP: redirect or unexpected response; stop for review")
                    data = response.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        raise CatalogError("HTTP: response exceeds size limit")
                    return data
            except HTTPError as exc:
                if exc.code not in (500, 502, 503, 504) or attempt == self.retries:
                    error = FetchFailed if exc.code in (500, 502, 503, 504) else CatalogError
                    raise error(f"HTTP {exc.code}: stopped; no bypass or automatic access retry") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt == self.retries:
                    raise FetchFailed(f"HTTP: retries exhausted: {exc}") from exc
            finally:
                self.last_finished = self.monotonic()
        raise CatalogError("HTTP: request failed")

    def get(self, url: str, *, max_bytes=4_000_000) -> bytes:
        if url not in self.allowed_urls:
            raise CatalogError("HTTP: URL has not been enabled after permission review")
        if type(max_bytes) is not int or max_bytes < 1:
            raise CatalogError("HTTP: max_bytes must be a positive integer")
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            text = self._request(origin + "/robots.txt", 128_000).decode("utf-8-sig")
            directives = [line.split("#", 1)[0].strip() for line in text.splitlines()]
            directives = [line for line in directives if line]
            # A nonempty comments-only robots file contains no restrictive directives.
            if ("<html" in text.lower() or not text.strip() or
                    (directives and not any(line.lower().startswith("user-agent:") for line in directives))):
                raise CatalogError("HTTP: robots.txt missing or unrecognized; stop for review")
            policy = RobotFileParser()
            policy.parse(text.splitlines())
            self.robots[origin] = policy
        policy = self.robots[origin]
        if not policy.can_fetch(USER_AGENT, url):
            raise CatalogError("HTTP: robots.txt prohibits this URL")
        crawl_delay = policy.crawl_delay(USER_AGENT)
        rate = policy.request_rate(USER_AGENT)
        if ((crawl_delay is not None and crawl_delay > self.min_delay) or
                (rate is not None and rate.seconds / rate.requests > self.min_delay)):
            raise CatalogError("HTTP: configured delay is shorter than robots.txt permits")
        return self._request(url, max_bytes)
