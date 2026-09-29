from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

# Covers common WhatsApp exports: 12/03/2024, 10:15 - Name: message;
# [12/03/2024, 10:15:00] Name: message; and 2024-03-12, 10:15 - Name: message.
MESSAGE_START = re.compile(
    r"^(?:\[)?(?:\d{1,4}[/-]\d{1,2}[/-]\d{1,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}),?\s+"
    r"\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APMapm]{2})?(?:\])?\s*-?\s*"
)
MEDIA_TOKEN = re.compile(r"(?P<name>[A-Za-z0-9][^\s:<>\"/\\|?*\x00-\x1f]*\.(?:jpe?g|png|gif|webp|heic|heif|bmp|tiff?))", re.I)


@dataclass
class ChatMedia:
    filename: str
    caption: str = ""


@dataclass
class ReportRow:
    source: str
    output: str = ""
    caption: str = ""
    status: str = ""
    detail: str = ""


def _clean_caption(value: str) -> str:
    value = value.replace("\u200e", "").replace("\ufeff", "")
    value = re.sub(r"\s+", " ", value).strip()
    value = INVALID_CHARS.sub("_", value)
    value = value.rstrip(" .")
    if not value:
        return ""
    if value.upper() in RESERVED_WINDOWS_NAMES:
        value = f"_{value}"
    return value[:180].rstrip(" .")


def _message_body(line: str) -> str:
    match = MESSAGE_START.match(line)
    if not match:
        return line.strip()
    body = line[match.end():]
    # Sender and message are separated by the first colon in standard exports.
    if ": " in body:
        return body.split(": ", 1)[1].strip()
    return body.strip()


def parse_chat(text: str) -> list[ChatMedia]:
    """Extract media filenames and captions from a WhatsApp export.

    Captions may be on the same line as the media filename or on continuation
    lines directly after it. A new timestamp ends a continuation caption.
    """
    entries: list[ChatMedia] = []
    pending: ChatMedia | None = None
    for raw_line in text.splitlines():
        # iOS exports may prefix every line with a left-to-right mark (U+200E).
        line = raw_line.replace("\u200e", "").replace("\ufeff", "").strip()
        if not line:
            continue
        is_new_message = bool(MESSAGE_START.match(line))
        if pending and not is_new_message:
            extra = line
            if extra.lower() not in {"<media omitted>", "(file attached)"}:
                pending.caption = f"{pending.caption} {extra}".strip()
            continue
        if pending:
            pending.caption = _clean_caption(pending.caption)
            entries.append(pending)
            pending = None

        body = _message_body(line)
        media = MEDIA_TOKEN.search(body)
        if not media:
            continue
        filename = Path(media.group("name")).name
        before = body[: media.start()].strip(" -:")
        before = re.sub(r"<\s*(?:adjunto|attached)\s*:?\s*$", "", before, flags=re.I).strip(" -:")
        after = body[media.end():].strip(" >")
        after = re.sub(r"\(?\s*(?:file attached|archivo adjunto)\s*\)?", "", after, flags=re.I).strip(" -:")
        pending = ChatMedia(filename=filename, caption=_clean_caption(after or before))
    if pending:
        pending.caption = _clean_caption(pending.caption)
        entries.append(pending)
    return entries


def unique_path(directory: Path, filename: str, reserved: set[str]) -> Path:
    candidate = directory / filename
    stem, suffix = candidate.stem, candidate.suffix
    index = 2
    while candidate.name.casefold() in reserved or candidate.exists():
        candidate = directory / f"{stem}_{index}{suffix}"
        index += 1
    reserved.add(candidate.name.casefold())
    return candidate


def process(media_dir: Path, output_dir: Path, chat_file: Path | None = None, dry_run: bool = False) -> list[ReportRow]:
    media_dir = media_dir.resolve()
    output_dir = output_dir.resolve()
    captions: dict[str, str] = {}
    if chat_file:
        text = chat_file.read_text(encoding="utf-8-sig", errors="replace")
        for item in parse_chat(text):
            captions[item.filename.casefold()] = item.caption or captions.get(item.filename.casefold(), "")

    files = sorted((p for p in media_dir.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
    rows: list[ReportRow] = []
    reserved: set[str] = set()
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    for source in files:
        if source.suffix.casefold() not in MEDIA_EXTENSIONS:
            rows.append(ReportRow(source.name, status="skipped", detail="unsupported_extension"))
            continue
        caption = captions.get(source.name.casefold(), "")
        if chat_file and source.name.casefold() not in captions:
            rows.append(ReportRow(source.name, status="not_in_chat", detail="media_not_referenced_in_chat"))
            continue
        base = _clean_caption(caption) if caption else source.stem
        destination = unique_path(output_dir, f"{base}{source.suffix}", reserved)
        row = ReportRow(source.name, destination.name, caption, "unchanged" if not caption else "processed")
        try:
            if not dry_run:
                shutil.copy2(source, destination)
            rows.append(row)
        except OSError as exc:
            row.status, row.detail = "error", str(exc)
            rows.append(row)
    if chat_file:
        referenced = {name.casefold() for name in captions}
        copied = {row.source.casefold() for row in rows}
        for missing in sorted(referenced - copied):
            rows.append(ReportRow(missing, status="missing_media", detail="referenced_by_chat_but_not_found"))
    return rows


def write_reports(rows: list[ReportRow], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "report.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "output", "caption", "status", "detail"])
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    (output_dir / "report.json").write_text(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")
