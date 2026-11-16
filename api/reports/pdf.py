"""Render a report to PDF with ReportLab (pure Python — no system
libraries, so the same code runs in the container, on a laptop and in
the test suite)."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .markup import inline, parse_blocks

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#5f6b7a")
BRAND = colors.HexColor("#1d4252")
RULE = colors.HexColor("#d5dbe1")
BAND = colors.HexColor("#eef2f5")

MARGIN = 0.85 * inch
PAGE_W, PAGE_H = LETTER

_base = ParagraphStyle(
    "base", fontName="Helvetica", fontSize=10, leading=14.5, textColor=INK, alignment=TA_LEFT
)
STYLES = {
    "body": ParagraphStyle("body", parent=_base, spaceAfter=7),
    "eyebrow": ParagraphStyle(
        "eyebrow", parent=_base, fontSize=9, leading=12, textColor=MUTED, spaceAfter=2
    ),
    "title": ParagraphStyle(
        "title", parent=_base, fontName="Helvetica-Bold", fontSize=22, leading=27,
        textColor=BRAND, spaceAfter=4,
    ),
    "subtitle": ParagraphStyle(
        "subtitle", parent=_base, fontSize=12, leading=16, textColor=MUTED, spaceAfter=18
    ),
    "section": ParagraphStyle(
        "section", parent=_base, fontName="Helvetica-Bold", fontSize=14, leading=18,
        textColor=BRAND, spaceBefore=14, spaceAfter=8,
    ),
    "h1": ParagraphStyle(
        "h1", parent=_base, fontName="Helvetica-Bold", fontSize=12, leading=16,
        spaceBefore=10, spaceAfter=5,
    ),
    "h2": ParagraphStyle(
        "h2", parent=_base, fontName="Helvetica-Bold", fontSize=10.5, leading=14,
        spaceBefore=9, spaceAfter=4,
    ),
    "cell": ParagraphStyle("cell", parent=_base, fontSize=8.5, leading=11),
    "cell_head": ParagraphStyle(
        "cell_head", parent=_base, fontName="Helvetica-Bold", fontSize=8.5, leading=11
    ),
}


def _table(rows: list[list[str]], width: float) -> Table:
    columns = max(len(r) for r in rows)
    data = []
    for i, row in enumerate(rows):
        style = STYLES["cell_head"] if i == 0 else STYLES["cell"]
        padded = row + [""] * (columns - len(row))
        data.append([Paragraph(inline(c), style) for c in padded])
    # Share the width in proportion to each column's longest cell, within
    # limits, so short columns stay narrow and names are not wrapped.
    weights = [
        min(36, max(8, *(len(row[c]) + 3 for row in rows if c < len(row))))
        for c in range(columns)
    ]
    widths = [width * w / sum(weights) for w in weights]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BAND),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, BRAND),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _flowables(text: str, width: float) -> list:
    out: list = []
    for block in parse_blocks(text):
        kind = block["type"]
        if kind == "paragraph":
            out.append(Paragraph("<br/>".join(inline(x) for x in block["lines"]), STYLES["body"]))
        elif kind == "heading":
            out.append(Paragraph(inline(block["text"]), STYLES[f"h{block['level']}"]))
        elif kind == "bullets":
            out.append(
                ListFlowable(
                    [ListItem(Paragraph(inline(i), STYLES["body"])) for i in block["items"]],
                    bulletType="bullet",
                    start="•",
                    leftIndent=14,
                    bulletFontSize=8,
                )
            )
            out.append(Spacer(1, 4))
        elif kind == "table":
            out.append(_table(block["rows"], width))
            out.append(Spacer(1, 10))
    return out


def render_pdf(
    *,
    title: str,
    customer: str,
    period_label: str,
    sections: list[dict],
    draft: bool,
    footer_note: str = "",
) -> bytes:
    """``sections`` is a list of ``{"title", "body"}`` with tags already
    filled. ``draft=True`` stamps every page so an unapproved copy can
    never be mistaken for the delivered one."""
    buffer = BytesIO()
    width = PAGE_W - 2 * MARGIN

    def decorate(canvas, doc) -> None:
        canvas.saveState()
        if draft:
            canvas.setFont("Helvetica-Bold", 96)
            canvas.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.12))
            canvas.translate(PAGE_W / 2, PAGE_H / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, -30, "DRAFT")
            canvas.restoreState()
            canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 0.62 * inch, PAGE_W - MARGIN, 0.62 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        left = f"Confidential — prepared for {customer}"
        if footer_note:
            left = f"{left} · {footer_note}"
        canvas.drawString(MARGIN, 0.45 * inch, left)
        canvas.drawRightString(PAGE_W - MARGIN, 0.45 * inch, f"Page {doc.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=0.9 * inch,
        title=title,
        author="AMS",
        subject=f"{customer} — {period_label}",
    )
    frame = Frame(MARGIN, 0.9 * inch, width, PAGE_H - MARGIN - 0.9 * inch, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=decorate)])

    story: list = [
        Paragraph(inline(customer.upper()), STYLES["eyebrow"]),
        Paragraph(inline(title), STYLES["title"]),
        Paragraph(inline(period_label), STYLES["subtitle"]),
    ]
    for section in sections:
        heading = Paragraph(inline(section.get("title") or ""), STYLES["section"])
        body = _flowables(section.get("body") or "", width)
        # Keep a section heading with whatever follows it.
        story.append(KeepTogether([heading, *body[:1]]))
        story.extend(body[1:])
    doc.build(story)
    return buffer.getvalue()
