"""Parse explicit identity fields in a saved Soshage detail page; no JavaScript evaluation."""

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

from gget_scanner.catalog.models import CatalogError, Unit, UnitImage, UnitSource, identity_id

# Confirmed by the user on 2026-10-30; preserve raw codes alongside these labels.
RARITY_CODES = {"1": "N", "2": "R", "3": "SR", "4": "SSR", "5": "UR"}
ROLE_CODES = {"1": "攻擊", "2": "耐久", "3": "支援"}


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_main = False
        self.heading = None
        self.headings = {"h1": [], "h2": []}
        self.images = []
        self.in_script = False
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "main":
            self.in_main = True
        if tag == "h1" or (tag == "h2" and self.in_main):
            self.heading = tag
            self.headings[tag].append("")
        if tag == "img" and self.in_main:
            self.images.append(attrs)
        if tag == "script":
            self.in_script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False
        if tag == self.heading:
            self.heading = None
        if tag == "script":
            self.in_script = False

    def handle_data(self, text):
        if self.heading:
            self.headings[self.heading][-1] += text
        if self.in_script:
            self.scripts[-1] += text


def parse_unit(html: str, page_url: str, *, retrieved_at: str | None = None) -> Unit:
    url = urlsplit(page_url)
    match = re.fullmatch(r"/gget/(zh-TW)/unit/([0-9]+)", url.path)
    if (url.scheme != "https" or url.netloc != "soshage.com" or not match or url.query or url.fragment):
        raise CatalogError("Soshage: expected canonical zh-TW unit detail URL")
    language, source_id = match.groups()
    page = _Page()
    page.feed(html)
    names = page.headings
    if not names["h1"] or not names["h2"]:
        raise CatalogError("Soshage: missing primary name headings")
    name = names["h2"][0].strip()
    if not name or names["h1"][0].strip() != name:
        raise CatalogError("Soshage: primary name headings disagree")

    # Only read the primary unit's scalar prefix, never weapons, stats, or related units.
    prefixes = re.findall(r'\bunit:\{(id:[0-9]+,(?:"(?:[^"\\]|\\.)*"|[^"{}])*?)stats:\{',
                          "\n".join(page.scripts), re.S)
    if len(prefixes) != 1:
        raise CatalogError("Soshage: missing or ambiguous primary unit data")
    prefix = prefixes[0]
    values = {}
    position = 0
    while position < len(prefix):
        field = re.match(r'([A-Za-z_]\w*):("(?:[^"\\]|\\.)*"|true|false|null|-?[0-9]+)(?:,|$)',
                         prefix[position:])
        if field is None or field[1] in values:
            raise CatalogError("Soshage: malformed or duplicate primary scalar field")
        values[field[1]] = json.loads(field[2])
        position += field.end()

    def scalar(key, *, string=False):
        value = values.get(key)
        if (string and not isinstance(value, str)) or (not string and type(value) is not int):
            raise CatalogError(f"Soshage: missing or ambiguous unit.{key}")
        return value if string else str(value)

    if scalar("id") != source_id or scalar("name", string=True) != name:
        raise CatalogError("Soshage: URL, unit ID and name disagree")
    icon, rarity_code, role_code = scalar("icon", string=True), scalar("rarity"), scalar("role")
    if re.fullmatch(r"g[0-9]+u[0-9]+", icon) is None:
        raise CatalogError("Soshage: unsupported primary image key")
    expected_path = f"/ggenet/profile/ub_{icon}.webp"
    primary = [i for i in page.images if urlsplit(i.get("src", "")).path == expected_path]
    if len(primary) != 1 or primary[0].get("alt") != name:
        raise CatalogError("Soshage: primary image key/name mismatch or missing image")
    image_url = primary[0]["src"]
    if urlsplit(image_url).scheme != "https" or urlsplit(image_url).netloc != "img.kusoge.xyz":
        raise CatalogError("Soshage: unexpected image host")
    rarity_icons = [i for i in page.images if urlsplit(i.get("src", "")).path ==
                    f"/ggenet/icon/UI_Common_RarityIcon_{rarity_code}.webp"]
    if not rarity_icons:
        raise CatalogError("Soshage: primary rarity icon disagrees with unit data")
    rarity = RARITY_CODES.get(rarity_code)
    label = rarity_icons[0].get("alt")
    if label in RARITY_CODES.values() and rarity is not None and label != rarity:
        raise CatalogError("Soshage: rarity label disagrees with numeric code")
    variant = "EX" if re.search(r"[（(]EX[)）]\s*$", name) else None
    source = UnitSource("soshage", source_id, page_url,
                        retrieved_at or datetime.now(timezone.utc).isoformat(), rarity_code, role_code)
    return Unit(identity_id("soshage", source_id), name, language, rarity, variant, ROLE_CODES.get(role_code),
                (source,), (UnitImage("artwork", image_url),))
