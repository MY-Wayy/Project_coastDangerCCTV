#!/usr/bin/env python3
"""최종보고서 Markdown → Word(.docx) 변환.

원본(포스터_보고서_섹션별_정리/00_부경대최우수상양식_최종보고서_통합본.md)은 읽기만 한다.
- 변환: pandoc (pypandoc_binary). 수식 ($...$, $$...$$)은 Word 네이티브 수식(OMML)으로 들어가 편집 가능
- 서식: pandoc 기본 reference.docx를 만든 뒤 A4·여백·맑은 고딕 글꼴로 고쳐서 사용
- 후처리 (python-docx): 그림·그림설명 가운데 정렬, 그림 크기 제한, 표 테두리·머리행 음영
- 이미지 alt 텍스트는 본문 아래 기울임 설명(<그림 n>)과 중복되므로 그림 캡션으로 쓰지 않는다

필요 패키지:  pip install pypandoc_binary python-docx
실행:  python build_report_docx.py   → 같은 폴더에 reference.docx 와 .docx 생성
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pypandoc
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent / "포스터_보고서_섹션별_정리" / "00_부경대최우수상양식_최종보고서_통합본.md"
OUT_DOCX = HERE / SRC.with_suffix(".docx").name
REF_DOCX = HERE / "reference.docx"

FONT = "맑은 고딕"
IMG_MAX_W = Cm(17.0)
IMG_MAX_H = Cm(12.5)
IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^)\s]+))\s*\)")

# 스타일 이름 → (글자 크기 pt, 굵게, 위 간격 pt, 아래 간격 pt)
STYLE_SPEC = {
    "Normal": (10.5, None, 0, 6),
    "Body Text": (10.5, None, 0, 6),
    "First Paragraph": (10.5, None, 0, 6),
    "Compact": (10.5, None, 0, 3),
    "Title": (19, True, 0, 10),
    "Heading 1": (19, True, 0, 10),
    "Heading 2": (14.5, True, 18, 8),
    "Heading 3": (12, True, 12, 6),
    "Block Text": (9.5, None, 0, 3),
}


def check_images(md_text: str) -> None:
    missing = [p for m in IMG_RE.finditer(md_text)
               if not (SRC.parent / (p := m.group(2) or m.group(3))).exists()]
    if missing:
        sys.exit("이미지 파일 없음:\n  " + "\n  ".join(missing))


def set_font(style_or_run, name: str = FONT) -> None:
    style_or_run.font.name = name
    rpr = style_or_run.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), name)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(attr), None)


def build_reference() -> None:
    with REF_DOCX.open("wb") as f:
        subprocess.run([pypandoc.get_pandoc_path(), "--print-default-data-file", "reference.docx"],
                       check=True, stdout=f)

    doc = Document(REF_DOCX)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin, sec.bottom_margin = Cm(1.8), Cm(2.0)
    sec.left_margin = sec.right_margin = Cm(1.6)

    for style in doc.styles:
        if style.type != 1:  # 문단 스타일만
            continue
        set_font(style)
        if style.name in STYLE_SPEC:
            size, bold, before, after = STYLE_SPEC[style.name]
            style.font.size = Pt(size)
            if bold is not None:
                style.font.bold = bold
            pf = style.paragraph_format
            pf.space_before, pf.space_after = Pt(before), Pt(after)
            pf.line_spacing = 1.2
        if style.name.startswith("Heading") or style.name == "Title":
            style.font.color.rgb = RGBColor(0x11, 0x11, 0x11)
            style.font.italic = False
    for name in ("Body Text", "First Paragraph"):
        doc.styles[name].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    doc.save(REF_DOCX)
    print("saved", REF_DOCX)


def convert() -> None:
    md_text = SRC.read_text(encoding="utf-8")
    check_images(md_text)
    pypandoc.convert_text(
        md_text, "docx", format="markdown-implicit_figures+tex_math_dollars",
        outputfile=str(OUT_DOCX),
        extra_args=[f"--reference-doc={REF_DOCX}", f"--resource-path={SRC.parent}"],
    )


def shade(cell, fill: str) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcpr.append(shd)


def border_table(table) -> None:
    tblpr = table._tbl.tblPr
    for old in tblpr.findall(qn("w:tblBorders")):
        tblpr.remove(old)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), "999999")
        borders.append(el)
    tblpr.append(borders)


def postprocess() -> None:
    doc = Document(OUT_DOCX)

    for shape in doc.inline_shapes:
        w, h = shape.width, shape.height
        scale = min(1.0, IMG_MAX_W / w, IMG_MAX_H / h)
        shape.width, shape.height = int(w * scale), int(h * scale)

    for p in doc.paragraphs:
        has_img = bool(p._p.findall(".//" + qn("w:drawing")))
        text = p.text.strip()
        is_caption = text.startswith("<그림") and all(r.italic for r in p.runs if r.text.strip())
        if has_img:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.space_before = Pt(8)
        if is_caption:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.font.size = Pt(9)
                r.font.color.rgb = RGBColor(0x44, 0x44, 0x44)

    for table in doc.tables:
        border_table(table)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, row in enumerate(table.rows):
            for cell in row.cells:
                if i == 0:
                    shade(cell, "E9E9E9")
                for p in cell.paragraphs:
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.0
                    for r in p.runs:
                        r.font.size = Pt(9)
                        if i == 0:
                            r.font.bold = True

    doc.save(OUT_DOCX)
    print("saved", OUT_DOCX, f"({OUT_DOCX.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    build_reference()
    convert()
    postprocess()


if __name__ == "__main__":
    main()
