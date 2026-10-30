from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from gget_scanner.catalog import CatalogError
from scripts.catalog_import.http import Fetcher


URL = "https://example.com/unit/1"
ROBOTS = "https://example.com/robots.txt"


class Response(BytesIO):
    status = 200

    def __init__(self, body, url):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url


def test_jitter_robots_timeout_identity_and_retry_are_bounded():
    waits, calls, ranges = [], [], []
    responses = [b"User-agent: *\nAllow: /\n", URLError("temporary"), b"ok", b"again"]

    def opener(request, timeout):
        calls.append((request.full_url, timeout, request.get_header("User-agent")))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return Response(item, request.full_url)

    def uniform(low, high):
        ranges.append((low, high))
        return low + len(ranges)

    fetch = Fetcher(allowed_urls=[URL], min_delay=8, max_delay=15, opener=opener,
                    sleep=waits.append, monotonic=lambda: 100.0, uniform=uniform)
    assert fetch.get(URL) == b"ok"
    assert fetch.get(URL) == b"again"
    assert waits == [9, 10, 11]
    assert ranges == [(8, 15)] * 3
    assert [c[0] for c in calls] == [ROBOTS, URL, URL, URL]
    assert all(c[1] == 20 and c[2] == "GGETCatalogImporter/0.1" for c in calls)


def test_no_permission_means_no_request():
    def forbidden(*args, **kwargs):
        raise AssertionError("network must not be called")

    with pytest.raises(CatalogError, match="permission review"):
        Fetcher(opener=forbidden).get(URL)


def test_comments_only_robots_has_no_directives_to_prohibit_fetching():
    def opener(request, timeout):
        return Response(b"# No directives\n# All comments\n" if request.full_url == ROBOTS else b"ok", request.full_url)
    assert Fetcher(allowed_urls=[URL], opener=opener, sleep=lambda _: None).get(URL) == b"ok"


@pytest.mark.parametrize("body", [b"User-agent: *\nDisallow: /unit/\n", b"<html>fallback</html>",
                                 b"User-agent: *\nCrawl-delay: 30\n", b""])
def test_blocked_ambiguous_or_slower_robots_never_fetch_data(body):
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(body, request.full_url)

    with pytest.raises(CatalogError):
        Fetcher(allowed_urls=[URL], opener=opener).get(URL)
    assert calls == [ROBOTS]


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429])
def test_access_errors_and_rate_limits_stop_without_retry(status):
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if request.full_url == ROBOTS:
            return Response(b"User-agent: *\nAllow: /\n", ROBOTS)
        raise HTTPError(URL, status, "stop", {}, None)

    with pytest.raises(CatalogError, match=str(status)):
        Fetcher(allowed_urls=[URL], opener=opener, sleep=lambda _: None).get(URL)
    assert calls == [ROBOTS, URL]


def test_retry_budget_and_response_size_limit():
    calls = []

    def offline(request, timeout):
        calls.append(request.full_url)
        raise URLError("offline")

    with pytest.raises(CatalogError, match="exhausted"):
        Fetcher(allowed_urls=[URL], opener=offline, sleep=lambda _: None).get(URL)
    assert len(calls) == 3

    def oversized(request, timeout):
        return Response(b"User-agent: *\nAllow: /\n" if request.full_url == ROBOTS else b"12345", request.full_url)

    with pytest.raises(CatalogError, match="size limit"):
        Fetcher(allowed_urls=[URL], opener=oversized, sleep=lambda _: None).get(URL, max_bytes=4)


@pytest.mark.parametrize("kwargs", [{"min_delay": 0}, {"min_delay": 10, "max_delay": 5},
                                    {"max_delay": float("inf")}, {"timeout": -1},
                                    {"retries": 3}, {"retries": True}])
def test_invalid_timing_settings(kwargs):
    with pytest.raises(CatalogError):
        Fetcher(**kwargs)
