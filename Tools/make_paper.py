#!/usr/bin/env python3
"""
Render Docs/Networked_MPLPB.md as a typeset PDF and a plain-text twin.

    python3 Tools/make_paper.py            # writes Docs/Networked_MPLPB.{pdf,txt}

A small hand-rolled renderer rather than a general Markdown engine, as in the
Smart Local repository: the paper uses a fixed subset (headings, paragraphs,
bullet and numbered lists, pipe tables, indented code blocks, block quotes,
rules, and bold / italic / code / <sub> spans), and a renderer that handles
exactly that subset is easier to check than one that handles everything.

The .txt twin needs only the standard library. The PDF needs reportlab
(`pip install reportlab`); it is the one dependency in the repository, and
it belongs to this tool, not to the package.
"""

from __future__ import annotations

import html
import re
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "Docs" / "Networked_MPLPB.md"

# --------------------------------------------------------------------------
# Parsing into blocks
# --------------------------------------------------------------------------


def blocks(md: str) -> list[tuple]:
    lines = md.splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            out.append(("h", level, line[level:].strip()))
            i += 1
        elif line.strip() == "---":
            out.append(("hr",))
            i += 1
        elif line.startswith("    "):
            buf = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                buf.append(lines[i][4:] if lines[i].strip() else "")
                i += 1
            while buf and not buf[-1]:
                buf.pop()
            out.append(("code", "\n".join(buf)))
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            out.append(("table", rows))
        elif line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip("> ").strip())
                i += 1
            out.append(("quote", " ".join(buf)))
        elif re.match(r"^(- |\d+\. )", line):
            items, nums, numbered = [], [], bool(re.match(r"^\d+\. ", line))
            while i < len(lines) and lines[i].strip():
                m = re.match(r"^(- |\d+\. )(.*)", lines[i])
                if m:
                    items.append(m.group(2))
                    nums.append(m.group(1).strip().rstrip("."))
                elif items:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append(("list", numbered, items, nums))
        else:
            buf = []
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||>|    |- |\d+\. |---)", lines[i]):
                buf.append(lines[i].strip())
                i += 1
            out.append(("p", " ".join(buf)))
    return out


# --------------------------------------------------------------------------
# Plain text
# --------------------------------------------------------------------------


def plain(text: str) -> str:
    text = re.sub(r"<sub>(.*?)</sub>", r"_\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = text.replace("`", "")
    return text


def table_txt(rows: list[list[str]], width: int = 78) -> str:
    rows = [[plain(c) for c in r] for r in rows]
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    gap = 2
    natural = [max(len(r[c]) for r in rows) for c in range(ncol)]
    minw = [min(max((len(w) for r in rows for w in r[c].split()), default=3), 24) for c in range(ncol)]
    avail = width - gap * (ncol - 1)
    widths = list(natural)
    while sum(widths) > avail:
        slack = [widths[j] - minw[j] for j in range(ncol)]
        j = max(range(ncol), key=lambda k: (slack[k] > 0, widths[k]))
        if slack[j] <= 0:
            j = widths.index(max(widths))
        widths[j] -= 1
    out = []
    sep = " " * gap
    for n, r in enumerate(rows):
        wrapped = [textwrap.wrap(cell, widths[c], break_on_hyphens=False) or [""] for c, cell in enumerate(r)]
        for k in range(max(len(w) for w in wrapped)):
            out.append(sep.join((w[k] if k < len(w) else "").ljust(widths[c]) for c, w in enumerate(wrapped)).rstrip())
        if n == 0:
            out.append(sep.join("-" * w for w in widths))
        elif len(rows) > 2 and any(len(w) > 1 for w in wrapped):
            out.append("")
    return "\n".join(out).rstrip()


def to_txt(md: str) -> str:
    out = []
    wrap = lambda t, ind="": textwrap.fill(plain(t), 78, initial_indent=ind, subsequent_indent=ind)
    for b in blocks(md):
        kind = b[0]
        if kind == "h":
            text = plain(b[2])
            if b[1] == 1:
                out.append("=" * 78 + "\n" + text.upper() + "\n" + "=" * 78)
            elif b[1] == 2:
                out.append(text + "\n" + ("=" if text[:1].isdigit() or text[:8] in ("Abstract", "Referenc", "Appendix") else "-") * len(text))
            else:
                out.append(text + "\n" + "-" * len(text))
        elif kind == "p":
            out.append(wrap(b[1]))
        elif kind == "hr":
            out.append("")
        elif kind == "code":
            out.append(textwrap.indent(b[1], "    "))
        elif kind == "quote":
            out.append(wrap(b[1], "    | "))
        elif kind == "list":
            items = []
            for n, it in zip(b[3], b[2]):
                bullet = f"{n}. " if b[1] else "- "
                items.append(textwrap.fill(plain(it), 78, initial_indent="  " + bullet,
                                           subsequent_indent=" " * (2 + len(bullet))))
            out.append("\n".join(items))
        elif kind == "table":
            out.append(table_txt(b[1]))
    return "\n\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = text.replace("&lt;sub&gt;", "<sub>").replace("&lt;/sub&gt;", "</sub>")
    text = re.sub(r"`([^`]+)`", r'<font face="Mono" size="8.6">\1</font>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    return text


def to_pdf(md: str, out: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.fonts import addMapping
    from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, KeepTogether, PageTemplate,
                                    Paragraph, Preformatted, Spacer, Table, TableStyle, ListFlowable,
                                    ListItem, CondPageBreak)

    fontdir = Path("/usr/share/fonts/truetype/dejavu")
    faces = {"Serif": "DejaVuSerif.ttf", "Serif-Bold": "DejaVuSerif-Bold.ttf",
             "Serif-Italic": "DejaVuSerif-Italic.ttf", "Serif-BoldItalic": "DejaVuSerif-BoldItalic.ttf",
             "Mono": "DejaVuSansMono.ttf", "Sans": "DejaVuSans.ttf", "Sans-Bold": "DejaVuSans-Bold.ttf"}
    if all((fontdir / f).exists() for f in faces.values()):
        for name, f in faces.items():
            pdfmetrics.registerFont(TTFont(name, str(fontdir / f)))
        addMapping("Serif", 0, 0, "Serif")
        addMapping("Serif", 1, 0, "Serif-Bold")
        addMapping("Serif", 0, 1, "Serif-Italic")
        addMapping("Serif", 1, 1, "Serif-BoldItalic")
        body, bold, ital, mono, sans = "Serif", "Serif-Bold", "Serif-Italic", "Mono", "Sans-Bold"
    else:  # fall back to the base-14 fonts
        body, bold, ital, mono, sans = "Times-Roman", "Times-Bold", "Times-Italic", "Courier", "Helvetica-Bold"
        pdfmetrics.registerFont  # noqa: B018 - base fonts need no registration

    INK, DIM = colors.HexColor("#12171C"), colors.HexColor("#5A6672")
    RULE, CARD, LINK = colors.HexColor("#D3DAE1"), colors.HexColor("#EFF2F4"), colors.HexColor("#2E4A7D")

    st = {
        "title": ParagraphStyle("title", fontName=bold, fontSize=24, leading=29, alignment=TA_CENTER, textColor=INK, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName=ital, fontSize=13.5, leading=18, alignment=TA_CENTER, textColor=DIM, spaceAfter=14),
        "author": ParagraphStyle("author", fontName=bold, fontSize=11.5, leading=15, alignment=TA_CENTER, textColor=INK),
        "affil": ParagraphStyle("affil", fontName=ital, fontSize=9.5, leading=13, alignment=TA_CENTER, textColor=DIM, spaceAfter=10),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=13.5, leading=17, textColor=INK, spaceBefore=16, spaceAfter=6),
        "h3": ParagraphStyle("h3", fontName=bold, fontSize=11, leading=14, textColor=LINK, spaceBefore=10, spaceAfter=4),
        "p": ParagraphStyle("p", fontName=body, fontSize=9.8, leading=13.9, alignment=TA_JUSTIFY, textColor=INK, spaceAfter=6),
        "li": ParagraphStyle("li", fontName=body, fontSize=9.8, leading=13.6, alignment=TA_JUSTIFY, textColor=INK),
        "quote": ParagraphStyle("quote", fontName=ital, fontSize=11, leading=15, alignment=TA_CENTER, textColor=LINK, spaceBefore=4, spaceAfter=10, leftIndent=24, rightIndent=24),
        "code": ParagraphStyle("code", fontName=mono, fontSize=7.8, leading=10.2, textColor=INK, backColor=CARD, borderPadding=(5, 6, 5, 6), spaceBefore=4, spaceAfter=9, leftIndent=6),
        "cell": ParagraphStyle("cell", fontName=body, fontSize=8.3, leading=10.6, textColor=INK),
        "head": ParagraphStyle("head", fontName=bold, fontSize=8.3, leading=10.6, textColor=INK),
    }

    story = []
    bl = blocks(md)
    # Title block: first h1, first h2, then two short paragraphs.
    assert bl[0][0] == "h" and bl[0][1] == 1
    story.append(Spacer(1, 0.25 * inch))
    story.append(Paragraph(inline(bl[0][2]), st["title"]))
    story.append(Paragraph(inline(bl[1][2]), st["subtitle"]))
    story.append(Paragraph(inline(bl[2][1]), st["author"]))
    story.append(Paragraph(inline(bl[3][1]), st["affil"]))
    rest = bl[4:]
    frame_width = letter[0] - 2 * 0.95 * inch

    for b in rest:
        kind = b[0]
        if kind == "h":
            style = st["h2"] if b[1] <= 2 else st["h3"]
            story.append(CondPageBreak(1.8 * inch if b[1] <= 2 else 1.2 * inch))
            story.append(Paragraph(inline(b[2]), style))
        elif kind == "p":
            story.append(Paragraph(inline(b[1]), st["p"]))
        elif kind == "hr":
            story.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceBefore=4, spaceAfter=6))
        elif kind == "quote":
            story.append(Paragraph(inline(b[1]), st["quote"]))
        elif kind == "code":
            story.append(Preformatted(b[1], st["code"]))
        elif kind == "list":
            li = ParagraphStyle("li2", parent=st["li"], leftIndent=20, bulletIndent=6, spaceAfter=3,
                                bulletFontName=body)
            for n, t in zip(b[3], b[2]):
                story.append(Paragraph(inline(t), li, bulletText=f"{n}." if b[1] else "\u2022"))
            story.append(Spacer(1, 4))
        elif kind == "table":
            rows = b[1]
            ncol = max(len(r) for r in rows)
            rows = [r + [""] * (ncol - len(r)) for r in rows]
            lens = [max(len(plain(r[c])) for r in rows) for c in range(ncol)]
            longest = [max((len(w) for r in rows for w in plain(r[c]).split()), default=4) for c in range(ncol)]
            floor = [min(l * 6.4 + 10, frame_width / 2.2) for l in longest]
            weights = [min(max(l, 6), 60) for l in lens]
            spare = max(0.0, frame_width - sum(floor))
            widths = [f + spare * w / sum(weights) for f, w in zip(floor, weights)]
            if sum(widths) > frame_width:
                widths = [w * frame_width / sum(widths) for w in widths]
            data = [[Paragraph(inline(c), st["head"] if n == 0 else st["cell"]) for c in r] for n, r in enumerate(rows)]
            t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), CARD),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(Spacer(1, 3))
            story.append(t)
            story.append(Spacer(1, 9))

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont(body, 7.8)
        canvas.setFillColor(DIM)
        if doc.page > 1:
            canvas.drawString(0.95 * inch, letter[1] - 0.6 * inch, "Networked MPLPB — Growing a Knowledge Network from a Seed")
            canvas.drawRightString(letter[0] - 0.95 * inch, letter[1] - 0.6 * inch, "M. D. McPhetridge · 2026")
            canvas.setStrokeColor(RULE)
            canvas.line(0.95 * inch, letter[1] - 0.66 * inch, letter[0] - 0.95 * inch, letter[1] - 0.66 * inch)
        canvas.drawCentredString(letter[0] / 2, 0.55 * inch, str(doc.page))
        canvas.restoreState()

    doc = BaseDocTemplate(str(out), pagesize=letter, leftMargin=0.95 * inch, rightMargin=0.95 * inch,
                          topMargin=0.9 * inch, bottomMargin=0.85 * inch,
                          title="Networked MPLPB: Growing a Knowledge Network from a Seed",
                          author="Mitchell D. McPhetridge",
                          subject="Federated self-describing knowledge corpora with verifiable provenance")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=decorate)])
    doc.build(story)


def main(argv: list[str]) -> int:
    outdir = Path(argv[1]) if len(argv) > 1 else SOURCE.parent
    md = SOURCE.read_text(encoding="utf-8")
    (outdir / "Networked_MPLPB.txt").write_text(to_txt(md), encoding="utf-8")
    try:
        to_pdf(md, outdir / "Networked_MPLPB.pdf")
    except ImportError:
        print("reportlab not installed; wrote the .txt twin only", file=sys.stderr)
        return 0
    print(f"wrote {outdir / 'Networked_MPLPB.pdf'} and {outdir / 'Networked_MPLPB.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
