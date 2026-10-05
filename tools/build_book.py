"""Build the reader's data files from the raw import + the editable book/book.json and book/products.json.

    python tools/import_pdf.py _import/source.pdf   # once per edition: page images + text into _import/
    python tools/build_book.py                       # every time book.json / products.json change

Outputs (all generated - do not hand-edit):
    book/pages/NNN.webp     full-resolution page images (zoom, high-DPI screens)
    book/md/NNN.webp        1100 px pages for the flip-book (light to decode and repaint)
    book/thumbs/NNN.webp    thumbnails
    book/text.json          clean page text for search
    book/words/NNN.json     text runs + item-code boxes per page
    book/parts.json         item code -> pages
    book/manifest.json      page list, titles, chapters, hotspots, product cards
"""
import difflib
import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone

from PIL import Image, ImageStat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMP = os.path.join(ROOT, "_import")
BOOK = os.path.join(ROOT, "book")
Q = 10000  # coordinates are stored as integers in 1/10000 of the page
MD_W = 1100  # width of the display-size page images used by the flip-book

ITEM_CODE = re.compile(r"^\d{6}$")                       # ITEM CODE : 410323
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")
URL = re.compile(r"^(https?://)?(www\.)?[a-z0-9-]+\.(com|sg|net|org)(/\S*)?$", re.I)
BOILERPLATE = [                                          # printed on every product sheet: noise in search results
    re.compile(r"^For orders please contact:?$", re.I),
    re.compile(r"^•?\s*Your HST Medical territory manager$", re.I),
    re.compile(r"^•?\s*resellercontact@hstmedical\.com$", re.I),
    re.compile(r"^Always read the label and$", re.I),
    re.compile(r"^follow directions for use$", re.I),
    re.compile(r"^•$"),
    re.compile(r"^.$"),                                    # "PRODUCT OF SINGAPORE" badge lettering, one letter per line
]


def load_runs(n):
    return json.load(open(os.path.join(IMP, "runs", f"{n:03d}.json"), encoding="utf-8"))


def tokens(run):
    """Split a run into space-separated tokens with their own boxes (via character widths)."""
    out, cw = [], run["cw"]
    if len(cw) != len(run["t"]):
        cw = [run["w"] / max(1, len(run["t"]))] * len(run["t"])
    for m in re.finditer(r"\S+", run["t"]):
        a, b = m.start(), m.end()
        out.append({"t": m.group(0), "x": run["x"] + sum(cw[:a]), "y": run["y"], "w": sum(cw[a:b]), "h": run["h"]})
    return out


def keep_run(r):
    return bool(r["t"].strip()) and r["t"].strip() != "•"


def q(v):
    return int(round(v * Q))


def box(ws):
    x0 = min(w["x"] for w in ws); y0 = min(w["y"] for w in ws)
    x1 = max(w["x"] + w["w"] for w in ws); y1 = max(w["y"] + w["h"] for w in ws)
    return x0, y0, x1 - x0, y1 - y0


def find_codes(toks):
    """6-digit item codes printed after 'ITEM CODE :' (same line, within a few tokens)."""
    codes = []
    for i, w in enumerate(toks):
        t = w["t"].strip(",;:()")
        if not ITEM_CODE.match(t):
            continue
        prev = [p for p in toks[max(0, i - 4):i] if abs(p["y"] - w["y"]) < 0.006]
        if any(p["t"].upper().startswith("CODE") for p in prev):
            codes.append((t, box([w])))
    return codes


def find_links(toks):
    links = []
    for w in toks:
        t = w["t"].strip().strip(",;:()").rstrip(".")
        if EMAIL.match(t):
            links.append({"type": "email", "href": "mailto:" + t, "label": t, "rect": box([w])})
        elif URL.match(t) and "." in t and "@" not in t:
            href = t if t.lower().startswith("http") else "https://" + t.lower()
            links.append({"type": "link", "href": href, "label": t.lower(), "rect": box([w])})
    return links


def norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[“”\"'’‘®™]", "", s.lower())
    s = s.replace("&", " ").replace("·", " ")
    return re.sub(r"[^a-z0-9+]+", " ", s).strip()


STOP = {"heritage", "capsules", "for", "with", "the", "and", "relief", "premium"}


def similarity(a, b):
    """Index entries are often longer than the sheet title ("Synbioten Probiotics + Prebiotics + Enzyme"
    vs "Synbioten"): reward containment as well as overlap, so the exact entry still wins."""
    ta, tb = set(norm(a).split()) - STOP, set(norm(b).split()) - STOP
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return (0.5 * inter / len(ta | tb) + 0.3 * inter / min(len(ta), len(tb))
            + 0.2 * difflib.SequenceMatcher(None, norm(a), norm(b)).ratio())


def index_hotspots(page, runs, chapters, products):
    """The 'Our Products' page: every product entry (and category heading) links to its page.
    Each entry is one text block in the PDF: name lines (8.5 pt) + pack line (7 pt)."""
    blocks = {}
    for r in runs:
        blocks.setdefault(r["b"], []).append(r)
    names = {p["page"]: p["name"] for p in products}
    # a product is matched on its sheet title or its full name from products.json, whichever fits best
    sections = [(t, p) for c in chapters for t, p in c["sections"]] + [(nm, p) for p, nm in names.items()]
    spots, used = [], set()
    for rs in blocks.values():
        heading = all(r["bold"] for r in rs)
        name = " ".join(r["t"].strip() for r in rs if r["s"] >= 8 and not (heading and r["s"] > 20))
        name = re.sub(r"-\s+", "-", name)
        if not name or max(r["s"] for r in rs) > 20:       # the page title "Our Products"
            continue
        pool = [(c["title"], c["page"]) for c in chapters] if heading else sections
        best = max(pool, key=lambda tp: similarity(name, tp[0]))
        score = similarity(name, best[0])
        if not heading:   # label with the sheet title, whichever name matched
            best = (next((t for c in chapters for t, p in c["sections"] if p == best[1]), best[0]), best[1])
        if score < 0.3:
            print(f"  index p.{page}: no match for {name!r}")
            continue
        x, y, w, h = box(rs)
        pad = 0.006
        spots.append({
            "page": page, "type": "page", "target": best[1],
            "label": (f"{best[0]} (category)" if heading else best[0]) + f" — p. {best[1]}",
            "rect": [round(x - pad, 4), round(y - pad, 4), round(min(w + 2 * pad, 0.19), 4), round(h + 2 * pad, 4)],
        })
        if not heading:
            used.add(best[1])
    missing = sorted({t for c in chapters for t, p in c["sections"] if p not in used})
    return spots, missing


def title_hotspot(page, runs, product):
    """The big product name (+ its tagline) opens the product card."""
    big = [r for r in runs if r["s"] >= 18 and r["x"] > 0.45]
    if not big:
        return None
    x, y, w, h = box(big)
    under = [r for r in runs if 9.5 <= r["s"] < 12 and r["x"] > 0.45 and 0 <= r["y"] - (y + h) < 0.03]
    if under:
        x, y, w, h = box(big + under[:1])
    pad = 0.008
    return {"page": page, "type": "product", "slug": product["slug"], "label": f"{product['name']} — pack sizes and item codes",
            "rect": [round(x - pad, 4), round(y - pad, 4), round(w + 2 * pad, 4), round(h + 2 * pad, 4)]}


def is_blank_image(path):
    im = Image.open(path).convert("L").resize((120, 170))
    st = ImageStat.Stat(im)
    return st.mean[0] > 250 and st.stddev[0] < 3


def main():
    cfg = json.load(open(os.path.join(BOOK, "book.json"), encoding="utf-8"))
    texts = json.load(open(os.path.join(IMP, "text.json"), encoding="utf-8"))
    prod_path = os.path.join(BOOK, "products.json")
    products = json.load(open(prod_path, encoding="utf-8"))["products"] if os.path.exists(prod_path) else []
    prod_by_page = {p["page"]: p for p in products}
    n_pages = len(texts)
    for d in ("pages", "thumbs", "words", "md"):
        os.makedirs(os.path.join(BOOK, d), exist_ok=True)

    # ---- page -> chapter / section titles from book.json -------------------------------
    chapter_of, section_of = {}, {}
    starts = []
    for ch in cfg["chapters"]:
        starts.append((ch["page"], ch, None))
        for title, p in ch["sections"]:
            starts.append((p, ch, title))
    starts.sort(key=lambda s: (s[0], s[2] is not None))
    last_ch = max(p for c in cfg["chapters"] for _, p in c["sections"])
    for i, (p, ch, title) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else last_ch + 1
        for pg in range(p, end):
            chapter_of[pg] = ch["no"]
            section_of[pg] = title

    def sync(src, dst):
        if (not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src)
                or os.path.getmtime(src) > os.path.getmtime(dst)):
            shutil.copyfile(src, dst)

    # a shorter new edition must not leave old pages behind
    for d in ("pages", "thumbs", "words", "md"):
        for f in os.listdir(os.path.join(BOOK, d)):
            m = re.match(r"(\d{3})\.", f)
            if m and int(m.group(1)) > n_pages:
                os.remove(os.path.join(BOOK, d, f))

    manifest_pages, all_codes, hotspots, missing_index = [], {}, [], []
    for n in range(1, n_pages + 1):
        src = os.path.join(IMP, "large", f"{n:03d}.webp")
        sync(src, os.path.join(BOOK, "pages", f"{n:03d}.webp"))
        sync(os.path.join(IMP, "thumb", f"{n:03d}.webp"), os.path.join(BOOK, "thumbs", f"{n:03d}.webp"))
        md = os.path.join(BOOK, "md", f"{n:03d}.webp")
        if not os.path.exists(md) or os.path.getmtime(src) > os.path.getmtime(md):
            im = Image.open(src).convert("RGB")
            im.resize((MD_W, round(im.height * MD_W / im.width)), Image.LANCZOS).save(md, "WEBP", quality=82, method=6)
        w_, h_ = Image.open(src).size

        runs = [r for r in load_runs(n) if keep_run(r)]
        toks = [t for r in runs for t in tokens(r)]
        codes = find_codes(toks)
        for code, (x, y, w, h) in codes:
            all_codes.setdefault(code, set()).add(n)
            # every printed item code copies itself on click (book, scroll and zoom views)
            hotspots.append({"page": n, "type": "code", "code": code, "label": f"Item code {code}: click to copy",
                             "rect": [round(x - 0.004, 4), round(y - 0.002, 4), round(w + 0.008, 4), round(h + 0.004, 4)]})
        for l in find_links(toks):
            hotspots.append({"page": n, "type": l["type"], "href": l["href"], "label": l["label"],
                             "rect": [round(v, 4) for v in l["rect"]], "auto": True})
        if n in cfg["settings"].get("indexPages", []):
            spots, missing_index = index_hotspots(n, runs, cfg["chapters"], products)
            hotspots += spots
        if n in prod_by_page:
            hs = title_hotspot(n, runs, prod_by_page[n])
            if hs:
                hotspots.append(hs)

        blank = not texts[n - 1].strip() and is_blank_image(src)
        with open(os.path.join(BOOK, "words", f"{n:03d}.json"), "w", encoding="utf-8") as f:
            json.dump({
                "w": [[r["t"], q(r["x"]), q(r["y"]), q(r["w"]), q(r["h"]), [q(c) for c in r["cw"]]] for r in runs],
                "p": [[c, q(b[0]), q(b[1]), q(b[2]), q(b[3])] for c, b in codes],
            }, f, ensure_ascii=False, separators=(",", ":"))

        label = cfg.get("pageLabels", {}).get(str(n))
        ch_no = chapter_of.get(n)
        if not label:
            if blank:
                label = "Blank page"
            elif ch_no and section_of.get(n) is None:
                ch = next(c for c in cfg["chapters"] if c["no"] == ch_no)
                label = ch["title"]
            else:
                label = section_of.get(n) or ""
        manifest_pages.append({"n": n, "w": w_, "h": h_, "blank": blank, "title": label,
                               "chapter": ch_no, "parts": len(codes)})

    # ---- clean search text --------------------------------------------------------------
    clean = []
    for t in texts:
        lines = [re.sub(r"^•\s*", "", l.strip()) for l in t.replace("\r", "").split("\n")]
        lines = [l for l in lines if l and not any(b.match(l) for b in BOILERPLATE)]
        clean.append("\n".join(lines))
    with open(os.path.join(BOOK, "text.json"), "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, separators=(",", ":"))

    # ---- product cards ------------------------------------------------------------------
    shop = cfg.get("shop", {})
    cards = {}
    for p in products:
        found = sorted(c for c, pages in all_codes.items() if p["page"] in pages)
        listed = [s["code"] for s in p.get("skus", [])]
        extra = [c for c in found if c not in listed]
        if extra or [c for c in listed if c not in found]:
            print(f"  p.{p['page']} {p['slug']}: codes on page {found} vs products.json {listed}")
        cards[str(p["page"])] = {
            "slug": p["slug"], "name": p["name"], "tagline": p.get("tagline", ""),
            "description": p.get("description", ""), "country": p.get("country", ""),
            "skus": p.get("skus", []),
            "url": shop.get("productUrl", "").replace("{slug}", p["slug"]) if shop.get("productUrl") else "",
        }

    pw, ph = manifest_pages[0]["w"], manifest_pages[0]["h"]
    manifest = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pageCount": n_pages,
        "pageSize": [pw, ph],
        "pages": manifest_pages,
        "hotspots": hotspots + cfg.get("hotspots", []),
        "products": cards,
        "stats": {"parts": len(all_codes), "partMentions": sum(len(v) for v in all_codes.values())},
    }
    with open(os.path.join(BOOK, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(BOOK, "parts.json"), "w", encoding="utf-8") as f:
        json.dump({c: sorted(p) for c, p in sorted(all_codes.items())}, f, separators=(",", ":"))

    kinds = {}
    for h in hotspots:
        kinds[h["type"]] = kinds.get(h["type"], 0) + 1
    print(f"pages {n_pages}  blanks {[p['n'] for p in manifest_pages if p['blank']]}")
    print(f"item codes {len(all_codes)} unique / {manifest['stats']['partMentions']} page mentions")
    print(f"hotspots {kinds}  product cards {len(cards)}")
    if missing_index:
        print("products not linked from the index page:", missing_index)


if __name__ == "__main__":
    sys.exit(main())
