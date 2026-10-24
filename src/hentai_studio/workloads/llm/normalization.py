"""Streaming, provenance-preserving cleanup for archived roleplay CSVs."""
from __future__ import annotations

import csv
import html
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path


_HARD_BREAKS = {"br", "p", "div", "li", "blockquote", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
_IGNORED_TAGS = {"script", "style", "noscript", "template", "svg"}
_INLINE_SPACE = re.compile(r"[ \t]+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in _HARD_BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in _HARD_BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def normalize_message(raw: str) -> str:
    """Remove presentation markup while preserving prose, actions, and breaks."""
    parser = _TextExtractor()
    try:
        parser.feed(html.unescape(raw))
        parser.close()
        text = "".join(parser.parts)
    except Exception:  # malformed forum HTML must not abort a 50 GB stream
        text = html.unescape(raw)
    text = unicodedata.normalize("NFKC", text).replace("\u200b", "").replace("\ufeff", "")
    lines = [_INLINE_SPACE.sub(" ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    compact: list[str] = []
    for line in lines:
        if line:
            compact.append(line)
        elif compact and compact[-1]:
            compact.append("")
    while compact and not compact[-1]:
        compact.pop()
    return "\n".join(compact)


@dataclass(slots=True)
class NormalizeReport:
    files: int = 0
    rows: int = 0
    kept_messages: int = 0
    empty_after_cleanup: int = 0
    documents: int = 0


def _document(title: str, href: str, turns: list[tuple[str, str]]) -> dict[str, object]:
    header = f"Thread: {title}" if title else "Roleplay thread"
    body = "\n\n".join(f"{speaker or 'Unknown'}:\n{text}" for speaker, text in turns)
    return {"text": f"{header}\n\n{body}", "source_thread": href, "turns": len(turns)}


def normalize_csv_archive(source: str | Path, output: str | Path, *, limit_files: int | None = None) -> NormalizeReport:
    source_root, output_root = Path(source), Path(output)
    files = sorted(source_root.glob("*.csv"))
    if limit_files is not None:
        files = files[:limit_files]
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"refusing to write into non-empty output directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    report = NormalizeReport()
    for input_path in files:
        report.files += 1
        target = output_root / f"{input_path.stem}.jsonl"
        partial = target.with_suffix(".jsonl.partial")
        current_href = current_title = ""
        turns: list[tuple[str, str]] = []
        with input_path.open(encoding="utf-8", errors="replace", newline="") as stream, partial.open("w", encoding="utf-8") as destination:
            def flush() -> None:
                nonlocal turns
                if turns:
                    destination.write(json.dumps(_document(current_title, current_href, turns), ensure_ascii=False) + "\n")
                    report.documents += 1
                turns = []

            for row in csv.DictReader(stream):
                report.rows += 1
                href = row.get("thread_href", "") or ""
                if turns and href != current_href:
                    flush()
                current_href, current_title = href, row.get("thread_title", "") or ""
                text = normalize_message(row.get("message", "") or "")
                if not text:
                    report.empty_after_cleanup += 1
                    continue
                turns.append((row.get("message_username", "") or "", text))
                report.kept_messages += 1
            flush()
        partial.replace(target)
    (output_root / "normalization-report.json").write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    return report
