from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from gget_scanner.catalog import CatalogError, load_catalog
from gget_scanner.catalog.loader import save_catalog
from gget_scanner.catalog.validator import validate_catalog
from scripts.catalog_import.crawl import Progress, _job_lock, run_crawl
from scripts.catalog_import.http import FetchFailed
from scripts.catalog_import.index import DATA_URL, LIST_URL, parse_index
from test_catalog_import import source_page


def index_html(count=3):
    rows = []
    for i in range(count):
        name = "測試機體 (EX)" if i % 2 else "測試機體"
        rows.append(dict(id=1001000150 + i, name=name, rarity=5, role=2))
    wrapper = json.dumps(dict(status=200, body=json.dumps(rows)))
    return f'<script type="application/json" data-url="{DATA_URL}">{wrapper}</script>'


class FakeFetcher:
    def __init__(self, count=3):
        self.allowed_urls = frozenset([LIST_URL])
        self.calls = []
        self.responses = {LIST_URL: index_html(count).encode()}
        image = cv2.imencode(".webp", np.full((8, 9, 3), 42, np.uint8))[1].tobytes()
        for i in range(count):
            html, url, image_url = source_page(i)
            self.responses[url] = html.encode()
            self.responses[image_url] = image

    def get(self, url, **kwargs):
        assert url in self.allowed_urls
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, BaseException):
            raise response
        return response


def test_index_contains_all_rarities_not_only_visible_links():
    rows = [dict(id=i, name=f"Unit {i}", rarity=i, role=1) for i in range(1, 6)]
    html = f'<script type="application/json" data-url="{DATA_URL}">' + json.dumps(
        dict(status=200, body=json.dumps(rows))) + '</script>'
    entries = parse_index(html)
    assert len(entries) == 5
    assert [e.rarity_code for e in entries] == ["1", "2", "3", "4", "5"]
    assert entries[0].page_url == LIST_URL + "/1"
    with pytest.raises(CatalogError):
        parse_index(html + html)
    with pytest.raises(CatalogError):
        parse_index("<html>challenge</html>")


def test_all_units_images_resume_and_ascii_terminal_logs(tmp_path, capsys):
    fake = FakeFetcher()
    result = run_crawl(root=tmp_path, fetcher=fake)
    assert result["reason"] == "completed"
    assert result["success"] == result["images_ready"] == 3
    catalog = load_catalog(tmp_path / "data/catalog/units.json")
    assert validate_catalog(catalog, tmp_path) == ()
    assert all(catalog.reference_paths(u.unit_id, tmp_path) for u in catalog.units)
    before = (tmp_path / "data/catalog/units.json").read_bytes()
    repeat = FakeFetcher()
    result = run_crawl(root=tmp_path, fetcher=repeat)
    assert result["skipped"] == 3
    assert repeat.calls == []
    assert (tmp_path / "data/catalog/units.json").read_bytes() == before
    stdout = capsys.readouterr().out
    assert stdout.isascii()
    assert "END | reason=completed" in stdout
    assert "images=3" in stdout


def test_count_limit_and_resume_use_same_index(tmp_path):
    first = run_crawl(root=tmp_path, limit=1, fetcher=FakeFetcher())
    assert first["reason"] == "count_limit"
    assert first["success"] == 1
    fake = FakeFetcher()
    resumed = run_crawl(root=tmp_path, fetcher=fake)
    assert resumed["reason"] == "completed"
    assert resumed["success"] == 2 and resumed["skipped"] == 1
    assert LIST_URL not in fake.calls


def test_three_temporary_failures_stop_and_remain_retryable(tmp_path):
    fake = FakeFetcher(5)
    for url in list(fake.responses):
        if url.startswith(LIST_URL + "/"):
            fake.responses[url] = FetchFailed("offline")
    result = run_crawl(root=tmp_path, fetcher=fake)
    assert result["reason"] == "consecutive_failures"
    assert result["failed"] == 3
    state = json.loads((tmp_path / "data/local_assets/cache/crawl/job.json").read_text())
    assert len(state["failed"]) == 3 and state["completed"] == []
    result = run_crawl(root=tmp_path, fetcher=FakeFetcher(5))
    assert result["reason"] == "completed" and result["success"] == 5


def test_access_denial_stops_immediately_and_persists_image_failure(tmp_path):
    fake = FakeFetcher()
    _, _, image_url = source_page()
    fake.responses[image_url] = CatalogError("HTTP 403: stopped")
    result = run_crawl(root=tmp_path, fetcher=fake)
    assert result["reason"] == "access_or_source_error"
    assert result["processed"] == 1
    image = load_catalog(tmp_path / "data/catalog/units.json").units[0].images[0]
    assert image.status == "failed" and "403" in image.error


def test_metadata_only_does_not_request_images_and_can_upgrade_later(tmp_path):
    fake = FakeFetcher(1)
    result = run_crawl(root=tmp_path, images=False, fetcher=fake)
    assert result["reason"] == "completed"
    assert len(fake.calls) == 2
    fake = FakeFetcher(1)
    result = run_crawl(root=tmp_path, images=True, fetcher=fake)
    assert result["images_ready"] == 1
    assert len(fake.calls) == 1  # Cached HTML, only image requested.


def test_interrupt_saves_previous_success_and_resumes(tmp_path):
    fake = FakeFetcher()
    _, url, _ = source_page(1)
    fake.responses[url] = KeyboardInterrupt()
    result = run_crawl(root=tmp_path, fetcher=fake)
    assert result["reason"] == "interrupted"
    assert len(load_catalog(tmp_path / "data/catalog/units.json").units) == 1
    result = run_crawl(root=tmp_path, fetcher=FakeFetcher())
    assert result["reason"] == "completed" and result["skipped"] == 1


def test_corrupted_cached_snapshot_stops_without_refetching(tmp_path):
    run_crawl(root=tmp_path, limit=1, fetcher=FakeFetcher())
    cache = tmp_path / "data/local_assets/cache/crawl"
    state = json.loads((cache / "job.json").read_text())
    (cache / state["index_file"]).write_text("corrupt")
    fake = FakeFetcher()
    result = run_crawl(root=tmp_path, fetcher=fake)
    assert result["reason"] == "fatal_error" and fake.calls == []


def test_existing_nonempty_conflict_is_preserved(tmp_path):
    run_crawl(root=tmp_path, limit=1, fetcher=FakeFetcher())
    path = tmp_path / "data/catalog/units.json"
    catalog = load_catalog(path)
    save_catalog(path, replace(catalog, units=(replace(catalog.units[0], name="Manual correction"),)))
    before = path.read_bytes()
    result = run_crawl(root=tmp_path, fetcher=FakeFetcher())
    assert result["reason"] == "access_or_source_error"
    assert path.read_bytes() == before


def test_job_lock_rejects_another_writer(tmp_path):
    with _job_lock(tmp_path / "crawl.lock"):
        with pytest.raises(CatalogError, match="already running"):
            with _job_lock(tmp_path / "crawl.lock"):
                pytest.fail("second writer acquired the lock")


def test_heartbeat_works_during_blocking_wait_and_closes(tmp_path, capsys):
    with Progress(tmp_path / "crawl.log", interval=0.01) as progress:
        progress.set("waiting for request")
        assert not progress.stopped.wait(0.04)
    assert "RUNNING | waiting for request" in capsys.readouterr().out
    assert not progress.thread.is_alive()


def test_invalid_checkpoint_is_not_overwritten(tmp_path):
    cache = tmp_path / "data/local_assets/cache/crawl"
    cache.mkdir(parents=True)
    path = cache / "job.json"
    path.write_text('{"version": 999}')
    before = path.read_bytes()
    result = run_crawl(root=tmp_path, fetcher=FakeFetcher())
    assert result["reason"] == "fatal_error"
    assert path.read_bytes() == before


def test_optional_time_limit_is_not_enabled_by_default(tmp_path):
    with patch("scripts.catalog_import.crawl.time.monotonic", side_effect=[0, 61]):
        result = run_crawl(root=tmp_path, max_minutes=1, fetcher=FakeFetcher())
    assert result["reason"] == "time_limit"
    assert result["processed"] == 0


def test_cli_defaults_to_entire_queue_with_images(tmp_path):
    from scripts.catalog_import.__main__ import main
    with patch("scripts.catalog_import.crawl.run_crawl", return_value={"reason": "completed"}) as worker:
        assert main(["crawl", "--root", str(tmp_path)]) == 0
    args = worker.call_args.kwargs
    assert args["images"] is True
    assert args["limit"] is None and args["max_minutes"] is None
    assert (args["min_delay"], args["max_delay"]) == (6, 9)


def test_checkpoint_does_not_claim_completion_during_work(tmp_path):
    fake = FakeFetcher(2)
    original_get = fake.get
    _, second_url, _ = source_page(1)

    def get(url, **kwargs):
        if url == second_url:
            state = json.loads((tmp_path / "data/local_assets/cache/crawl/job.json").read_text())
            assert state["stop_reason"] == "running"
            assert len(state["completed"]) == 1
        return original_get(url, **kwargs)

    fake.get = get
    assert run_crawl(root=tmp_path, fetcher=fake)["reason"] == "completed"
