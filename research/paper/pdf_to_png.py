"""Render PDF pages to PNG for visual checks.   python pdf_to_png.py in.pdf outdir [dpi] [first_page] [last_page]"""
import sys
from pathlib import Path

import pypdfium2 as pdfium

src, out = Path(sys.argv[1]), Path(sys.argv[2])
dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 70
first = int(sys.argv[4]) if len(sys.argv) > 4 else 1
pdf = pdfium.PdfDocument(str(src))
last = int(sys.argv[5]) if len(sys.argv) > 5 else len(pdf)
out.mkdir(parents=True, exist_ok=True)
for i in range(first - 1, min(last, len(pdf))):
    pdf[i].render(scale=dpi / 72).to_pil().save(out / f"page_{i + 1:02d}.png")
print(f"{len(pdf)} pages; wrote {first}..{min(last, len(pdf))} to {out}")
