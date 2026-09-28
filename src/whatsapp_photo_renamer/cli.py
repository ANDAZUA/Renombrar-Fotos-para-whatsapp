from __future__ import annotations

import argparse
from pathlib import Path

from .core import process, write_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Rename WhatsApp exported photos using captions")
    parser.add_argument("--media", required=True, type=Path, help="Folder containing exported media")
    parser.add_argument("--chat", type=Path, help="WhatsApp exported chat TXT")
    parser.add_argument("--output", required=True, type=Path, help="Destination folder")
    parser.add_argument("--dry-run", action="store_true", help="Generate reports without copying photos")
    args = parser.parse_args()
    if not args.media.is_dir():
        parser.error(f"Media folder does not exist: {args.media}")
    if args.chat and not args.chat.is_file():
        parser.error(f"Chat file does not exist: {args.chat}")
    rows = process(args.media, args.output, args.chat, args.dry_run)
    write_reports(rows, args.output)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    print(f"Completed: {len(rows)} files | " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print(f"Reports: {args.output / 'report.csv'} and {args.output / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
