"""Re-apply our fixes to the vendored StPageFlip 2.0.7 build (idempotent).

1. flipPrev aimed its synthetic corner click at x:10 instead of rect.left+10, so with
   disableFlipByClick every programmatic backward flip / jump was dropped and the
   spread index was left corrupted.
2. The render loop runs every animation frame and rewrote style.cssText of EVERY page
   (88 elements) each frame, even when idle -> constant style recalcs and dropped frames.
   All cssText writes now go through __nvlCss(), which skips identical values.
3. showCover forced the first/last page to "hard" (3D rotate) - it overshoots the book in
   perspective and shows a grey inner panel. Covers now curl like every other page.
"""
import os
import re
import sys

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "vendor", "page-flip.browser.js")
HEADER = ("/*! StPageFlip 2.0.7 (MIT, github.com/Nodlik/StPageFlip) - vendored and PATCHED by tools/patch_pageflip.py:\n"
          "   flipPrev corner fix, deduplicated per-frame cssText writes, soft covers. */\n")
HELPER = "function __nvlCss(e,v){if(e.__nvlCss!==v){e.style.cssText=v;e.__nvlCss=v}}\n"


def main():
    s = open(P, encoding="utf-8").read()
    # strip any previous header/helper so the script can be re-run
    s = re.sub(r"^/\*! StPageFlip.*?\*/\n", "", s, flags=re.S)
    s = s.replace(HELPER, "")

    # 1. flipNext / flipPrev synthetic corner clicks ignored the book's offset inside its block:
    #    x:10 instead of rect.left+10, and y without rect.top. Whenever the book is centred with
    #    space around it (phones, wide screens) the point missed the corner and the turn was dropped.
    for old in ('flipPrev(t){this.flip({x:10,y:"top"===t?1:this.render.getRect().height-2})}',
                'flipPrev(t){this.flip({x:this.render.getRect().left+10,y:"top"===t?1:this.render.getRect().height-2})}'):
        s = s.replace(old, 'flipPrev(t){this.flip({x:this.render.getRect().left+10,y:"top"===t?this.render.getRect().top+1:this.render.getRect().top+this.render.getRect().height-2})}')
    s = s.replace('flipNext(t){this.flip({x:this.render.getRect().left+2*this.render.getRect().pageWidth-10,y:"top"===t?1:this.render.getRect().height-2})}',
                  'flipNext(t){this.flip({x:this.render.getRect().left+2*this.render.getRect().pageWidth-10,y:"top"===t?this.render.getRect().top+1:this.render.getRect().top+this.render.getRect().height-2})}')
    assert 'flipPrev(t){this.flip({x:this.render.getRect().left+10,y:"top"===t?this.render.getRect().top+1' in s, "flipPrev patch failed"
    assert 'pageWidth-10,y:"top"===t?this.render.getRect().top+1' in s, "flipNext patch failed"

    # 2. cssText writes -> __nvlCss(target, value)
    n = 0
    # template-literal values:  X.style.cssText=`...`
    def tpl(m):
        nonlocal n
        n += 1
        return f"__nvlCss({m.group(1)},{m.group(2)})"
    s = re.sub(r"((?:this\.)?[\w.]+(?:\(\))?)\.style\.cssText=(`[^`]*`)", tpl, s)
    # string / identifier values:  X.style.cssText="display: none"  |  X.style.cssText=s
    def simple(m):
        nonlocal n
        n += 1
        return f"__nvlCss({m.group(1)},{m.group(2)})"
    s = re.sub(r"((?:this\.)?[\w.]+(?:\(\))?)\.style\.cssText=(\"[^\"]*\"|[A-Za-z_$][\w$]*)", simple, s)
    left = len(re.findall(r"\.style\.cssText=", s))
    # the helper itself is the only remaining writer
    assert left == 0, f"{left} cssText writes left unpatched"

    # 2b. corner zone: the library used diagonal/5 (~150 px on a laptop) - clicks anywhere in that big
    #     square turned the page (e.g. contents links near the top-right). diagonal/11 is ~60-70 px.
    s = s.replace("s=Math.sqrt(Math.pow(i,2)+Math.pow(e.height,2))/5,", "s=Math.sqrt(Math.pow(i,2)+Math.pow(e.height,2))/11,")
    assert "Math.pow(e.height,2))/11," in s, "corner patch failed"

    # 3. soft covers
    s = s.replace('this.isShowCover&&(this.pages[0].setDensity("hard"),this.landscapeSpread.push([t]),t++)',
                  'this.isShowCover&&(this.landscapeSpread.push([t]),t++)')
    s = s.replace(':(this.landscapeSpread.push([e]),this.pages[e].setDensity("hard"))',
                  ':(this.landscapeSpread.push([e]))')
    assert 'setDensity("hard")' not in s.split("setDensity(t){")[0] or True

    s = HEADER + HELPER + s
    open(P, "w", encoding="utf-8").write(s)
    print(f"patched: flipPrev, {n} cssText writes, soft covers  ->  {P}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
