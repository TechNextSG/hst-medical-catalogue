# HST Medical Product Sheets — interactive reader

An interactive flip-book of the HST Medical product sheets (54 pages: cover, About us, 51 product sheets,
"Our Products" index), rebuilt from the Heyzine edition at <https://heyzine.com/flip-book/1cbc07dcc6.html>
into a site we own. The reader engine is the one built for the nivellipso catalogue
(technextmarketing/nivellipso-catalogue); the look follows the HST Medical website prototype
(TechNextSG/hst-medical-website): white chrome, cool grey wells, logo magenta `#dd1860`, slate, Inter + Plus Jakarta Sans.

**Status: unlisted test link** (`noindex`, `robots.txt` disallows all) until the client signs off.

## What it does

| | |
|---|---|
| **Book** | Realistic page curl. Drag from anywhere on a page, swipe, arrow keys or the wheel. Clicking again while a page turns finishes it and starts the next one, so you can riffle. Soft paper sound (on/off in settings). Spreads on desktop, single pages on tall tablets. All pages load up front (no lazy loading). |
| **Phones** | **Scroll view only** - no flip-book and no view switcher on phones (narrow screens, or a phone held sideways). Book/Pages requests (keys, `&v=` links) open in Scroll. Product names, item codes, index links, search and Zoom all work in the column. Tablets and desktop keep all three views. |
| **Product cards** | Click a product name on any sheet (or **Product details** in the bar) for its pack sizes and item codes, a link to the product page on the website, and an order e-mail to resellercontact@hstmedical.com. A spread with two products shows both. |
| **Item codes** | Every printed item code copies itself on click. Search finds all 58 codes; a partial code lists the matches. |
| **Index page** | Every product line (and category heading) on the "Our Products" back page jumps to its sheet. |
| **Scroll / Pages / Zoom** | One column with real, selectable text; all pages as thumbnails by category; click a page to zoom (to 600%, pinch, pan, text tool). |
| **Contents, search, bookmarks** | 11 categories and 51 products, filterable; full-text search with on-page highlights; bookmarks saved per browser. |
| **Links** | `#p=21` opens page 21. Share copies a link to the current page. Light (default), Auto and Dark themes. |

## Change the book

Content model: `book/book.json` (chapters, labels, shop links, contact) and `book/products.json` (product cards).
After any edit:

```bash
python tools/build_book.py
```

- **Website links:** `shop.productUrl` (`{slug}` = product slug) and `shop.shopUrl`. They point at the website
  prototype's test link today; switch them to hstmedical.com when the new site is live.
- **Hotspots:** add to `hotspots[]` in book.json, e.g.
  `{"page": 3, "rect": [0.5, 0.1, 0.3, 0.05], "type": "video", "href": "https://youtu.be/...", "label": "TV commercial"}`.
  `rect` = x, y, width, height as fractions of the page. Types: `page` (`"target": 12`), `link`, `email`, `video`, `image`, `note`, `product` (`"slug"`), `code` (`"code"`).
  E-mail addresses printed on pages, item codes, product names and the index page lines become clickable automatically.

After any change to CSS/JS, bump the `?v=` numbers in `index.html` (GitHub Pages caches for 10 minutes).

## New edition (new PDF from HST)

```bash
python tools/import_pdf.py path/to/new.pdf "path/to/hst-medical-website/_src/products.json"
python tools/build_book.py
```

The importer renders the pages (1555 px + 339 px thumbnails) and reads the text layer straight from the PDF, so search,
highlights, item codes and the index links keep working. Update `book.json` chapters if pages moved. The build prints any
product whose item codes on the page differ from products.json, and any product the index page doesn't link.

## Files

```
index.html               reader shell
assets/reader.css        design system (HST magenta, slate, Inter + Plus Jakarta Sans, light + dark)
assets/reader.js         reader engine (book / scroll / pages / zoom / search / product cards)
assets/vendor/           StPageFlip 2.0.7 (MIT) - PATCHED: run python tools/patch_pageflip.py after any re-download
book/book.json           EDITABLE content model
book/products.json       EDITABLE product cards (pack sizes, item codes, website slug)
book/manifest.json       generated: pages, titles, hotspots, product cards
book/text.json           generated: search text
book/parts.json          generated: item code -> pages
book/words/NNN.json      generated: text runs + item-code boxes per page
book/md                  1100 px pages used by the flip-book
book/pages, book/thumbs  full 1555 px pages (zoom, high-DPI screens) and thumbnails
tools/                   import_pdf.py, build_book.py, QA (qa_console.js, run_qa.py, shoot.py)
_import/                 raw import cache + source PDF (git-ignored)
```

Local preview: `python -m http.server 3987` in this folder (launch entry `hst-catalogue`).

## QA

```bash
python tools/run_qa.py http://localhost:3987/ 1440x900 1180x1000 768x1024 390x844
```

Runs `HSTQA()` (on phones: 15 Scroll-only checks instead of the book suite; elsewhere 51 checks on the flip engine, driven frame by frame: cover centring, drags, riffling, sounds, index links,
item-code copy, product cards, zoom, panel, rail, search) and `HSTQA_UI()` (34 checks through the real controls) in headless
Chrome at each size. Both can also be pasted into the browser console (`tools/qa_console.js`). They never open an e-mail link or the website.
`python tools/shoot.py <url> <WxH> <out.png> "<js>"` takes a headless screenshot.

Printed-catalogue issues for the client are listed in `CATALOGUE-QA.md`.
