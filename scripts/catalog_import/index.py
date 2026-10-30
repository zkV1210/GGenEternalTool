"""Read the actual unit array embedded in a public Soshage list snapshot."""

from dataclasses import dataclass
from html.parser import HTMLParser
import json

from gget_scanner.catalog.models import CatalogError

LIST_URL = "https://soshage.com/gget/zh-TW/unit"
DATA_URL = "/ggetapi/zh-TW/unit?order_by=rarity:desc"


@dataclass(frozen=True)
class IndexEntry:
    source_id: str
    name: str
    rarity_code: str
    role_code: str

    @property
    def page_url(self):
        return f"{LIST_URL}/{self.source_id}"


class _Index(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/json" and attrs.get("data-url") == DATA_URL:
            self.active = True
            self.blocks.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False

    def handle_data(self, text):
        if self.active:
            self.blocks[-1] += text


def parse_index(html: str) -> tuple[IndexEntry, ...]:
    parser = _Index()
    parser.feed(html)
    if len(parser.blocks) != 1:
        raise CatalogError("Index: missing or ambiguous embedded unit array")
    try:
        wrapper = json.loads(parser.blocks[0])
        if not isinstance(wrapper, dict) or type(wrapper.get("status")) is not int or wrapper["status"] != 200:
            raise CatalogError("Index: embedded request was not successful")
        rows = json.loads(wrapper["body"])
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise CatalogError("Index: invalid embedded JSON") from exc
    if not isinstance(rows, list) or not rows:
        raise CatalogError("Index: expected a nonempty unit array")
    entries, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0 or
                not isinstance(row.get("name"), str) or not row["name"].strip() or
                type(row.get("rarity")) is not int or type(row.get("role")) is not int):
            raise CatalogError("Index: invalid unit identity fields")
        if row["id"] in seen:
            raise CatalogError("Index: duplicate source ID")
        seen.add(row["id"])
        entries.append(IndexEntry(str(row["id"]), row["name"], str(row["rarity"]), str(row["role"])))
    return tuple(sorted(entries, key=lambda e: int(e.source_id)))
