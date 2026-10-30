"""One-pass, resumable public-page crawl with bounded requests and English logs."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from threading import Event, Lock, Thread
import time

from gget_scanner.catalog.loader import atomic_json, load_catalog, save_catalog
from gget_scanner.catalog.models import Catalog, CatalogError
from gget_scanner.catalog.validator import check_image, image_info, local_image_path

from .http import Fetcher, FetchFailed
from .importer import _copy_image, _event, import_manifest
from .index import LIST_URL, parse_index
from .soshage import RARITY_CODES, ROLE_CODES, parse_unit


def _ascii(value):
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


class Progress:
    def __init__(self, path, interval=15):
        self.stream = path.open("a", encoding="utf-8")
        self.message = "Starting"
        self.interval = interval
        self.stopped = Event()
        self.lock = Lock()
        self.error = None
        self.thread = Thread(target=self._heartbeat, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def emit(self, message):
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp} +08:00 | {_ascii(message)}"
        with self.lock:
            print(line, flush=True)
            self.stream.write(line + "\n")
            self.stream.flush()

    def set(self, message):
        if self.error is not None:
            raise OSError(f"Log write failed: {self.error}")
        self.message = message

    def _heartbeat(self):
        while not self.stopped.wait(self.interval):
            try:
                self.emit("RUNNING | " + self.message)
            except OSError as exc:
                self.error = exc
                return

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join()
        self.stream.close()


@contextmanager
def _job_lock(path):
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CatalogError("Another crawl process is already running") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _snapshot(cache, prefix, data):
    name = f"{prefix}-{sha256(data).hexdigest()}.html"
    path = cache / name
    if path.exists():
        if path.read_bytes() != data:
            raise CatalogError("Snapshot is damaged; refusing to overwrite")
        return name
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return name


def _read_snapshot(cache, name):
    path = local_image_path(cache, name)
    data = path.read_bytes()
    if not path.name.endswith(f"-{sha256(data).hexdigest()}.html"):
        raise CatalogError("Snapshot checksum mismatch")
    return data.decode("utf-8-sig")


def _matches(unit, entry):
    return (unit.name == entry.name and unit.rarity == RARITY_CODES.get(entry.rarity_code) and
            unit.rarity is not None and unit.role == ROLE_CODES.get(entry.role_code) and unit.role is not None and
            any(s.source == "soshage" and s.source_id == entry.source_id and s.page_url == entry.page_url and
                s.rarity_code == entry.rarity_code and s.role_code == entry.role_code for s in unit.sources) and
            any(i.kind == "artwork" and i.source_url for i in unit.images))


def _images_ready(unit, root):
    images = [i for i in unit.images if i.kind == "artwork"]
    for image in images:
        if image.status != "downloaded":
            return False
        try:
            check_image(image, root)
        except CatalogError:
            return False
    return bool(images)


def _download_images(unit, catalog, root, cache, fetcher):
    images = list(unit.images)
    failure = None
    try:
        for index, image in enumerate(images):
            if image.kind != "artwork":
                continue
            try:
                if image.status == "downloaded":
                    check_image(image, root)
                    continue
            except CatalogError:
                pass
            fetcher.allowed_urls |= frozenset([image.source_url])
            try:
                data = fetcher.get(image.source_url, max_bytes=10_000_000)
                image_info(data)
            except CatalogError as exc:
                images[index] = replace(image, status="failed", error=str(exc))
                failure = exc
                break
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                stored = _copy_image(temporary, image, root)
                if stored.status != "downloaded":
                    raise OSError(stored.error)
                images[index] = stored
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    finally:
        updated = replace(unit, images=tuple(images))
        if updated != unit:
            catalog = replace(catalog, units=tuple(updated if u.unit_id == unit.unit_id else u for u in catalog.units))
            save_catalog(root / "data/catalog/units.json", catalog)
    if failure is not None:
        raise failure
    return updated


def run_crawl(*, root=".", images=True, min_delay=6.0, max_delay=9.0,
              limit=None, max_minutes=None, index_html=None, refresh_index=False, fetcher=None):
    """Defaults process the entire pinned index once, including artwork downloads."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise CatalogError("limit must be a positive integer")
    if max_minutes is not None and (not math.isfinite(max_minutes) or max_minutes <= 0):
        raise CatalogError("max-minutes must be a finite positive number")
    root = Path(root).resolve()
    cache = root / "data/local_assets/cache/crawl"
    cache.mkdir(parents=True, exist_ok=True)
    fetcher = fetcher or Fetcher(allowed_urls=[LIST_URL], min_delay=min_delay, max_delay=max_delay)
    with _job_lock(cache / "crawl.lock"), Progress(cache / "crawl.log") as progress:
        return _run(root, cache, progress, fetcher, images, limit, max_minutes, index_html, refresh_index)


def _run(root, cache, progress, fetcher, images, limit, max_minutes, index_html, refresh_index):
    state_path = cache / "job.json"
    state = {"version": 1, "index_file": None, "pages": {}, "failed": {}, "completed": []}
    counts = dict(processed=0, success=0, skipped=0, failed=0, images_ready=0)
    reason = "starting"
    started = time.monotonic()

    def checkpoint():
        state.update(stop_reason=reason, counts=counts.copy(), images_requested=images,
                     updated_at=datetime.now(timezone.utc).isoformat())
        atomic_json(state_path, state)

    try:
        if state_path.exists():
            previous = json.loads(state_path.read_text(encoding="utf-8"))
            if (not isinstance(previous, dict) or previous.get("version") != 1 or
                    not isinstance(previous.get("pages"), dict) or not isinstance(previous.get("failed"), dict) or
                    not isinstance(previous.get("completed"), list) or not isinstance(previous.get("index_file"), str)):
                raise CatalogError("Invalid crawl checkpoint; stop for review")
            state = previous
            if refresh_index:
                atomic_json(cache / f"previous-job-{sha256(state_path.read_bytes()).hexdigest()}.json", previous)
                state = {"version": 1, "index_file": None, "pages": {}, "failed": {}, "completed": []}
            elif index_html is not None:
                raise CatalogError("A pinned job exists; use --refresh-index to replace its index")
        if state["index_file"] is None:
            progress.set("Fetching public unit index")
            progress.emit("START | Building unit queue; no default count or time limit")
            data = Path(index_html).read_bytes() if index_html is not None else fetcher.get(LIST_URL, max_bytes=40_000_000)
            entries = parse_index(data.decode("utf-8-sig"))
            state["index_file"] = _snapshot(cache, "index", data)
        else:
            entries = parse_index(_read_snapshot(cache, state["index_file"]))
        state["total"] = len(entries)
        checkpoint()
        fetcher.allowed_urls |= frozenset(e.page_url for e in entries)
        progress.emit(f"QUEUE | total={len(entries)} | images={'enabled' if images else 'disabled'}")
        output = root / "data/catalog/units.json"
        catalog = load_catalog(output) if output.exists() else Catalog(())
        known = {s.source_id: u for u in catalog.units for s in u.sources if s.source == "soshage"}
        consecutive = 0
        reason = "running"
        for number, entry in enumerate(entries, 1):
            if max_minutes is not None and time.monotonic() - started >= max_minutes * 60:
                reason = "time_limit"
                break
            unit = known.get(entry.source_id)
            progress.set(f"{number}/{len(entries)} | success={counts['success']} skipped={counts['skipped']} failed={counts['failed']} images={counts['images_ready']} | checking unit={entry.source_id}")
            if unit is not None and _matches(unit, entry) and (not images or _images_ready(unit, root)):
                counts["skipped"] += 1
                if images:
                    counts["images_ready"] += 1
                state["failed"].pop(entry.source_id, None)
                if entry.source_id not in state["completed"]:
                    state["completed"].append(entry.source_id)
                checkpoint()
                continue
            if limit is not None and counts["processed"] >= limit:
                reason = "count_limit"
                break
            counts["processed"] += 1
            status = f"{number}/{len(entries)} | success={counts['success']} skipped={counts['skipped']} failed={counts['failed']} images={counts['images_ready']} | unit={entry.source_id}"
            progress.set(status + " | fetching or waiting")
            try:
                page_file = state["pages"].get(entry.source_id)
                if page_file is None:
                    data = fetcher.get(entry.page_url, max_bytes=2_000_000)
                    page_file = _snapshot(cache, entry.source_id, data)
                    state["pages"][entry.source_id] = page_file
                    checkpoint()
                candidate = parse_unit(_read_snapshot(cache, page_file), entry.page_url)
                if not _matches(candidate, entry):
                    raise CatalogError("Detail page disagrees with pinned index or contains unknown codes")
                manifest = cache / "current-unit.json"
                atomic_json(manifest, [{"page_url": entry.page_url, "html_path": page_file}])
                imported = import_manifest(manifest, root=root, limit=1)
                if imported["conflicts"] or imported["errors"]:
                    raise CatalogError("Import conflict or parse failure; see import_events.jsonl")
                catalog = load_catalog(output)
                unit = next(u for u in catalog.units if any(s.source == "soshage" and s.source_id == entry.source_id for s in u.sources))
                if images:
                    progress.set(status + " | downloading or verifying image")
                    unit = _download_images(unit, catalog, root, cache, fetcher)
                    counts["images_ready"] += 1
                known[entry.source_id] = unit
                state["failed"].pop(entry.source_id, None)
                if entry.source_id not in state["completed"]:
                    state["completed"].append(entry.source_id)
                counts["success"] += 1
                consecutive = 0
                progress.emit(f"OK | {number}/{len(entries)} | unit={entry.source_id} | success={counts['success']} skipped={counts['skipped']} failed={counts['failed']} images={counts['images_ready']}")
            except FetchFailed as exc:
                counts["failed"] += 1
                consecutive += 1
                state["failed"][entry.source_id] = str(exc)
                _event(cache / "errors.jsonl", source_id=entry.source_id, error=str(exc))
                progress.emit(f"FAILED | unit={entry.source_id} | consecutive={consecutive}/3 | {exc}")
                if consecutive >= 3:
                    reason = "consecutive_failures"
                    break
            except CatalogError as exc:
                counts["failed"] += 1
                state["failed"][entry.source_id] = str(exc)
                _event(cache / "errors.jsonl", source_id=entry.source_id, error=str(exc))
                reason = "access_or_source_error"
                progress.emit(f"STOP | unit={entry.source_id} | {exc}")
                break
            checkpoint()
        else:
            reason = "completed"
        if reason == "completed" and state["failed"]:
            reason = "finished_with_errors"
    except KeyboardInterrupt:
        reason = "interrupted"
    except (OSError, CatalogError, ValueError) as exc:
        reason = "fatal_error"
        progress.emit(f"STOP | {exc}")
        # Never replace an unreadable pre-existing checkpoint with an empty job.
        if state["index_file"] is None:
            return {"reason": reason, **counts}
    finally:
        if state["index_file"] is not None:
            checkpoint()
    progress.emit(f"END | reason={reason} | success={counts['success']} skipped={counts['skipped']} failed={counts['failed']} images={counts['images_ready']} | progress saved")
    if not images:
        progress.emit("METADATA ONLY | local artwork files have not been downloaded")
    return {"reason": reason, **counts}
