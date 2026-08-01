import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "面试问答整理.md"
OUT_DIR = ROOT / "output" / "pdf"
OUT = OUT_DIR / "智扫通智能客服项目面试问答整理.pdf"


def register_fonts():
    candidates = [
        Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
        Path("C:/Windows/Fonts/SourceHanSansCN-Normal.ttf"),
        Path("C:/Windows/Fonts/Deng.ttf"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    ]
    for font_path in candidates:
        if font_path.exists():
            pdfmetrics.registerFont(TTFont("CJK", str(font_path)))
            return "CJK"
    return "Helvetica"


FONT = register_fonts()


def clean_inline(text: str) -> str:
    text = text.strip()
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName=FONT,
            fontSize=22,
            leading=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=8 * mm,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName=FONT,
            fontSize=10,
            leading=16,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#334155"),
            spaceAfter=10 * mm,
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName=FONT,
            fontSize=15,
            leading=22,
            textColor=colors.HexColor("#0F5F5C"),
            spaceBefore=7 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName=FONT,
            fontSize=11,
            leading=17,
            textColor=colors.HexColor("#0F172A"),
            spaceBefore=3 * mm,
            spaceAfter=1.5 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=FONT,
            fontSize=9.5,
            leading=16,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#111827"),
            spaceAfter=2.4 * mm,
        ),
        "quote": ParagraphStyle(
            "quote",
            fontName=FONT,
            fontSize=9.2,
            leading=15,
            leftIndent=5 * mm,
            rightIndent=3 * mm,
            textColor=colors.HexColor("#111827"),
            borderColor=colors.HexColor("#94A3B8"),
            borderWidth=0.8,
            borderPadding=5,
            backColor=colors.HexColor("#F9FAFB"),
            spaceBefore=2 * mm,
            spaceAfter=3 * mm,
        ),
        "list": ParagraphStyle(
            "list",
            fontName=FONT,
            fontSize=9.2,
            leading=15,
            textColor=colors.HexColor("#111827"),
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName=FONT,
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#475569"),
        ),
    }


styles = make_styles()


def header_footer(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.line(18 * mm, height - 15 * mm, width - 18 * mm, height - 15 * mm)
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#334155"))
    canvas.drawString(18 * mm, height - 11 * mm, "智扫通机器人智能客服系统")
    canvas.drawRightString(width - 18 * mm, 9 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def parse_markdown(md: str):
    story = []
    lines = md.splitlines()
    i = 0
    first_title = True

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if not line or line == "---":
            i += 1
            continue

        if line.startswith("# "):
            if first_title:
                story.append(Paragraph(clean_inline(line[2:]), styles["title"]))
                story.append(
                    Paragraph("面试官提问视角 - 应聘者回答口径", styles["subtitle"])
                )
                first_title = False
            else:
                story.append(PageBreak())
                story.append(Paragraph(clean_inline(line[2:]), styles["h1"]))
            i += 1
            continue

        if line.startswith("## "):
            story.append(Paragraph(clean_inline(line[3:]), styles["h1"]))
            i += 1
            continue

        if line.startswith("**") and line.endswith("**"):
            story.append(Paragraph(clean_inline(line), styles["h2"]))
            i += 1
            continue

        if line.startswith(">"):
            story.append(Paragraph(clean_inline(line.lstrip("> ")), styles["quote"]))
            i += 1
            continue

        if re.match(r"^\d+\.\s+", line):
            items = []
            while i < len(lines):
                item_line = lines[i].strip()
                if not re.match(r"^\d+\.\s+", item_line):
                    break
                item_text = re.sub(r"^\d+\.\s+", "", item_line)
                items.append(
                    ListItem(Paragraph(clean_inline(item_text), styles["list"]))
                )
                i += 1
            story.append(
                ListFlowable(
                    items, bulletType="1", leftIndent=8 * mm, bulletFontName=FONT
                )
            )
            story.append(Spacer(1, 1.5 * mm))
            continue

        para = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (
                not nxt
                or nxt == "---"
                or nxt.startswith(("#", "**", ">"))
                or re.match(r"^\d+\.\s+", nxt)
            ):
                break
            para.append(nxt)
            i += 1
        story.append(Paragraph(clean_inline(" ".join(para)), styles["body"]))

    return story


def build_pdf():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md = SOURCE.read_text(encoding="utf-8")
    story = parse_markdown(md)

    doc = BaseDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="智扫通智能客服项目面试问答整理",
        author="Codex",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates(
        [PageTemplate(id="main", frames=[frame], onPage=header_footer)]
    )
    doc.build(story)


if __name__ == "__main__":
    build_pdf()
    print(OUT)
