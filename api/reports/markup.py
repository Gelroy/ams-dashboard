"""Light markup → blocks.

Section text (after tags are filled) uses a small subset of Markdown so
staff can lay a report out in a plain text box:

    ## Sub-heading
    - bullet
    | Column A | Column B |      first row is the header
    | value    | value    |
    **bold**

Everything else is a paragraph; a blank line starts a new one and single
line breaks are kept. The result is a list of JSON-friendly blocks that
the PDF renderer walks.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

_PIPE = "\x00"
_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
#: ``[[like this]]`` marks something staff still have to write or check.
TODO_MARK = re.compile(r"\[\[(.+?)\]\]")


def _cells(line: str) -> list[str]:
    inner = line.strip().replace("\\|", _PIPE)
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    return [c.strip().replace(_PIPE, "|") for c in inner.split("|")]


def parse_blocks(text: str) -> list[dict]:
    blocks: list[dict] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append({"type": "paragraph", "lines": paragraph.copy()})
            paragraph.clear()

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("|"):
            flush()
            cells = _cells(line)
            if all(_SEPARATOR_CELL.match(c) for c in cells if c) and any(cells):
                continue  # a |---|---| ruler row
            if blocks and blocks[-1]["type"] == "table":
                blocks[-1]["rows"].append(cells)
            else:
                blocks.append({"type": "table", "rows": [cells]})
        elif line.startswith("## "):
            flush()
            blocks.append({"type": "heading", "level": 2, "text": line[3:].strip()})
        elif line.startswith("# "):
            flush()
            blocks.append({"type": "heading", "level": 1, "text": line[2:].strip()})
        elif line.startswith(("- ", "* ")):
            flush()
            item = line[2:].strip().replace("\\|", "|")
            if blocks and blocks[-1]["type"] == "bullets":
                blocks[-1]["items"].append(item)
            else:
                blocks.append({"type": "bullets", "items": [item]})
        else:
            paragraph.append(line.replace("\\|", "|"))
    flush()
    return blocks


def inline(text: str) -> str:
    """Escape text for a ReportLab Paragraph and apply **bold**."""
    return _BOLD.sub(r"<b>\1</b>", escape(text))


def todo_marks(text: str) -> list[str]:
    return [m.group(1).strip() for m in TODO_MARK.finditer(text)]
