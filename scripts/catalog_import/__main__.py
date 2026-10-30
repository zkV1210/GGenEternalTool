"""Run from repository root: python -m scripts.catalog_import --help."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from gget_scanner.catalog.loader import load_catalog
from gget_scanner.catalog.models import CatalogError
from gget_scanner.catalog.validator import validate_catalog

from .importer import import_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local unit catalog import, validation and resumable crawling.")
    sub = parser.add_subparsers(dest="command", required=True)
    importer = sub.add_parser("import", help="Import saved HTML and explicitly supplied local images")
    importer.add_argument("manifest", type=Path)
    importer.add_argument("--root", type=Path, default=Path.cwd())
    importer.add_argument("--limit", type=int, default=15, help="Maximum manifest entries to process (default: 15)")
    validator = sub.add_parser("validate", help="Validate metadata, image hashes and decoding")
    validator.add_argument("--root", type=Path, default=Path.cwd())
    crawler = sub.add_parser("crawl", help="Process the complete public unit index once; resume automatically")
    crawler.add_argument("--root", type=Path, default=Path.cwd())
    crawler.add_argument("--no-images", action="store_true", help="Import metadata and image URLs only")
    crawler.add_argument("--min-delay", type=float, default=6.0, help="Minimum request wait in seconds (default: 6)")
    crawler.add_argument("--max-delay", type=float, default=9.0, help="Maximum request wait in seconds (default: 9)")
    crawler.add_argument("--limit", type=int, help="Optional maximum pending units to attempt; default: entire index")
    crawler.add_argument("--max-minutes", type=float, help="Optional time limit, checked between units; default: none")
    crawler.add_argument("--index-html", type=Path, help="Use a saved public list HTML for a new job")
    crawler.add_argument("--refresh-index", action="store_true", help="Start from a new index; preserve previous job snapshot")
    args = parser.parse_args(argv)
    try:
        if args.command == "crawl":
            from .crawl import run_crawl
            result = run_crawl(root=args.root, images=not args.no_images, min_delay=args.min_delay,
                               max_delay=args.max_delay, limit=args.limit, max_minutes=args.max_minutes,
                               index_html=args.index_html, refresh_index=args.refresh_index)
            return 0 if result["reason"] == "completed" else 130 if result["reason"] == "interrupted" else 1
        if args.command == "import":
            result = import_manifest(args.manifest, root=args.root, limit=args.limit)
            print(json.dumps(result, ensure_ascii=False))
            return 1 if any(result[k] for k in ("errors", "conflicts", "validation_issues")) else 0
        issues = validate_catalog(load_catalog(args.root / "data/catalog/units.json"), args.root)
        print(json.dumps([asdict(i) for i in issues], ensure_ascii=False, indent=2))
        return 1 if issues else 0
    except (CatalogError, OSError, UnicodeError) as exc:
        message = str(exc)
        if args.command == "crawl":
            message = message.encode("ascii", "backslashreplace").decode("ascii")
        parser.exit(2, f"catalog: {message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
