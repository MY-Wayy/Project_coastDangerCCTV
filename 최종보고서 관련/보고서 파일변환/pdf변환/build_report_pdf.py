#!/usr/bin/env python3
"""최종보고서 Markdown → HTML → PDF 변환.

원본(포스터_보고서_섹션별_정리/00_부경대최우수상양식_최종보고서_통합본.md)은 읽기만 한다.
- 이미지: 파일을 base64로 HTML에 직접 넣어 경로 문제를 없앤다 (없는 파일이 있으면 중단)
- 수식 ($...$, $$...$$): pymdownx.arithmatex → KaTeX(cdnjs)로 렌더링
- PDF: Chrome 헤드리스 인쇄 (A4, 머리글·바닥글 없음)

실행:  python build_report_pdf.py   → 같은 폴더에 .html 과 .pdf 생성
"""

from __future__ import annotations

import base64
import re
import subprocess
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent / "포스터_보고서_섹션별_정리" / "00_부경대최우수상양식_최종보고서_통합본.md"
OUT_HTML = HERE / SRC.with_suffix(".html").name
OUT_PDF = HERE / SRC.with_suffix(".pdf").name
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^)\s]+))\s*\)")


def embed_images(md_text: str) -> str:
    missing: list[str] = []

    def repl(m: re.Match) -> str:
        alt, path = m.group(1), (m.group(2) or m.group(3))
        p = (SRC.parent / path).resolve()
        if not p.exists():
            missing.append(path)
            return m.group(0)
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        return f'<figure><img src="data:{mime};base64,{data}" alt="{alt}"></figure>'

    out = IMG_RE.sub(repl, md_text)
    if missing:
        sys.exit("이미지 파일 없음:\n  " + "\n  ".join(missing))
    return out


CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
html { font-size: 10.5pt; }
/* Pretendard(웹폰트)를 1순위로: Apple SD Gothic Neo로 인쇄하면 PDF 텍스트 레이어의 띄어쓰기가
   제어문자(\x01)로 저장되어 AI·검색 도구가 단어를 붙여 읽는다. Pretendard는 공백이 정상 저장됨 */
body {
  font-family: "Pretendard", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic", "Malgun Gothic", sans-serif;
  color: #111; line-height: 1.65; margin: 0; word-break: keep-all;
}
h1 { font-size: 19pt; line-height: 1.35; margin: 0 0 10pt; text-wrap: balance; }
h2 { font-size: 14.5pt; margin: 20pt 0 8pt; padding-bottom: 4pt; border-bottom: 1.5px solid #333; break-after: avoid; }
h3 { font-size: 12pt; margin: 14pt 0 6pt; break-after: avoid; }
p { margin: 0 0 7pt; text-align: justify; }
blockquote { margin: 0 0 10pt; padding: 6pt 10pt; border-left: 3px solid #888; background: #f4f4f4; font-size: 9.5pt; }
blockquote p { margin: 0 0 3pt; text-align: left; }
ul, ol { margin: 0 0 8pt; padding-left: 1.4em; }
li { margin-bottom: 3pt; }
hr { border: 0; border-top: 1px solid #ccc; margin: 12pt 0; }
code { font-family: Menlo, "SF Mono", monospace; font-size: 0.9em; background: #f0f0f0; padding: 0 3px; border-radius: 3px; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9pt; break-inside: avoid; }
th, td { border: 1px solid #999; padding: 4pt 6pt; vertical-align: top; text-align: left; }
th { background: #e9e9e9; font-weight: 700; }
figure { margin: 10pt 0 2pt; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; max-height: 125mm; height: auto; }
figure + p > em:only-child, p > em:only-child { display: block; text-align: center; font-size: 9pt; color: #444; margin: 2pt 0 10pt; }
.katex-display { margin: 8pt 0 10pt; overflow-x: auto; }
.katex { font-size: 1.02em; }
"""

HEAD = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>{title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.11/katex.min.css">
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.11/katex.min.js"></script>
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.11/contrib/auto-render.min.js"></script>
<script>
document.addEventListener("DOMContentLoaded", function () {{
  renderMathInElement(document.body, {{
    delimiters: [
      {{left: "\\\\[", right: "\\\\]", display: true}},
      {{left: "\\\\(", right: "\\\\)", display: false}}
    ],
    throwOnError: false
  }});
}});
</script>
<style>{css}</style></head><body>
"""


def main() -> None:
    md_text = SRC.read_text(encoding="utf-8")
    md_text = embed_images(md_text)
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "attr_list", "md_in_html", "sane_lists",
                    "pymdownx.arithmatex"],
        extension_configs={"pymdownx.arithmatex": {"generic": True}},
    )
    title = re.search(r"^# (.+)$", md_text, re.M)
    html = HEAD.format(title=title.group(1) if title else SRC.stem, css=CSS) + html_body + "\n</body></html>\n"
    OUT_HTML.write_text(html, encoding="utf-8")
    print("saved", OUT_HTML, f"({OUT_HTML.stat().st_size / 1e6:.1f} MB)")

    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           "--virtual-time-budget=20000", "--run-all-compositor-stages-before-draw",
           f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()]
    subprocess.run(cmd, check=True, capture_output=True)
    print("saved", OUT_PDF, f"({OUT_PDF.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
