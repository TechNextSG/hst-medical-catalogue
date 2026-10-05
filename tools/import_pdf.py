"""Import a new edition straight from the print PDF (InDesign export).

    python tools/import_pdf.py _import/source.pdf [path/to/products.json]
    python tools/build_book.py

Writes the raw import cache (git-ignored) that build_book.py reads:
    _import/large/NNN.webp    1555 px wide page images (zoom, high-DPI screens)
    _import/thumb/NNN.webp    339 px thumbnails
    _import/runs/NNN.json     text runs with per-character widths (search, highlights, selectable text, hotspots)
    _import/text.json         plain page text (search index)

The optional products.json (from the HST website prototype, _src/products.json) is copied to
book/products.json: the product cards (pack sizes, item codes, website links) are built from it.
The PDF is the source of truth for page content: re-run this whenever HST sends a new edition.
"""
import json
import os
import re
import sys

import pymupdf
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMP = os.path.join(ROOT, "_import")
PAGE_W, THUMB_W = 1555, 339
FLAGS = pymupdf.TEXT_INHIBIT_SPACES | pymupdf.TEXT_PRESERVE_WHITESPACE   # letter-spaced headings stay one word


def clean(t):
    t = t.replace("\t", " ").replace(" ", " ").replace("\n", "")
    return t


def runs_of(page):
    """One run per text span (a phrase in one font), coordinates as fractions of the page."""
    W, H = page.rect.width, page.rect.height
    out = []
    for bi, b in enumerate(page.get_text("rawdict", flags=FLAGS)["blocks"]):
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            if abs(l["dir"][1]) > 0.01:          # curved badge lettering ("PRODUCT OF SINGAPORE") is not text
                continue
            for s in l["spans"]:
                chars = [c for c in s["chars"] if c["c"] not in "\n\r"]
                # leading/trailing whitespace carries no position worth keeping
                while chars and not chars[0]["c"].strip():
                    chars.pop(0)
                while chars and not chars[-1]["c"].strip():
                    chars.pop()
                if not chars:
                    continue
                t = clean("".join(c["c"] for c in chars))
                x0 = chars[0]["bbox"][0]
                x1 = max(c["bbox"][2] for c in chars)
                y0, y1 = s["bbox"][1], s["bbox"][3]
                # per-character advance: distance to the next character (includes tracking), own width for the last
                cw = []
                for i, c in enumerate(chars):
                    nx = chars[i + 1]["bbox"][0] if i + 1 < len(chars) else c["bbox"][2]
                    cw.append(max(0.0, nx - c["bbox"][0]) / W)
                out.append({
                    "t": t, "x": x0 / W, "y": y0 / H, "w": (x1 - x0) / W, "h": (y1 - y0) / H,
                    "cw": cw, "s": round(s["size"], 1), "b": bi,
                    "bold": "Bold" in s["font"] or "Semibold" in s["font"],
                })
    return out


def page_text(page):
    t = page.get_text("text", flags=FLAGS)
    t = t.replace("\t", " ").replace(" ", " ")
    t = re.sub(r"[ ]{2,}", " ", t)
    return "\n".join(l.strip() for l in t.split("\n") if l.strip())


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pdf = pymupdf.open(sys.argv[1])
    for d in ("large", "thumb", "runs"):
        os.makedirs(os.path.join(IMP, d), exist_ok=True)
    texts = []
    for i, page in enumerate(pdf, 1):
        scale = PAGE_W / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        im.save(os.path.join(IMP, "large", f"{i:03d}.webp"), "WEBP", quality=86, method=6)
        th = round(im.height * THUMB_W / im.width)
        im.resize((THUMB_W, th), Image.LANCZOS).save(os.path.join(IMP, "thumb", f"{i:03d}.webp"), "WEBP", quality=80)
        with open(os.path.join(IMP, "runs", f"{i:03d}.json"), "w", encoding="utf-8") as f:
            json.dump(runs_of(page), f, ensure_ascii=False, separators=(",", ":"))
        texts.append(page_text(page))
        print(f"{i:03d}  {im.width}x{im.height}")
    with open(os.path.join(IMP, "text.json"), "w", encoding="utf-8") as f:
        json.dump(texts, f, ensure_ascii=False, indent=0)
    # remove pages left over from a longer edition
    for d in ("large", "thumb", "runs"):
        for name in os.listdir(os.path.join(IMP, d)):
            m = re.match(r"(\d{3})\.", name)
            if m and int(m.group(1)) > len(pdf):
                os.remove(os.path.join(IMP, d, name))
    if len(sys.argv) > 2:
        src = json.load(open(sys.argv[2], encoding="utf-8"))
        keep = ("slug", "name", "tagline", "description", "country", "skus")
        prods = []
        for p in src["products"]:
            m = re.match(r"p(\d+)$", p.get("image", ""))
            if not m:
                continue
            prods.append({"page": int(m.group(1)), **{k: p[k] for k in keep if k in p}})
        prods.sort(key=lambda p: p["page"])
        with open(os.path.join(ROOT, "book", "products.json"), "w", encoding="utf-8") as f:
            json.dump({"_readme": "Product cards, one per product page (page = real page number). Imported from the "
                       "website prototype's _src/products.json by tools/import_pdf.py; edit freely, then run build_book.py.",
                       "products": prods}, f, ensure_ascii=False, indent=1)
        print(f"products.json: {len(prods)} products")
    print(f"imported {len(pdf)} pages - now run: python tools/build_book.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
