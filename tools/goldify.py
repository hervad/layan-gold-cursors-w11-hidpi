#!/usr/bin/env python3
"""Generate the gold SVGs for w11cursor (run from the repo root, before `w11cursor build`).

    python tools/goldify.py          # src/svg/*.svg -> build/gold/*.svg

The gold style - palette, brown outline, help-glyph tuning - is moved here VERBATIM from the v2.0.1 build.py
(goldify / tune_help_glyph and their constants); only the file handling below is new. The SVGs in src/svg are
vendored unmodified from vinceliuice/Layan-cursors (commit b8c4689, "svg" variant).
"""

from __future__ import annotations

import io
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import resvg_py
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG_DIR = ROOT / "src" / "svg"
OUT_DIR = ROOT / "build" / "gold"

# The SVGs are drawn on a 32-unit grid, the same as Windows' nominal 32 px.
SVG_GRID = 32

# --- Gold style ---------------------------------------------------------------
GOLD_LIGHT = "#fff0ab"
GOLD_DEEP = "#ffcd42"
GOLD_SOLID = "#ffdf77"  # for shapes upstream fills with a flat color
OUTLINE = "#392310"
OUTLINE_WIDTH = 1  # SVG units, painted under the fill so ~half shows outside

# Upstream gradient stops -> gold. Each family is (light end, deep end).
GRADIENT_STOPS = {
    "#716ffb": GOLD_LIGHT, "#4648fb": GOLD_DEEP,  # pointer bodies (blue)
    "#cd2ec5": GOLD_LIGHT, "#21c4d6": GOLD_DEEP,  # bars, brackets, rings
    "#ffc107": GOLD_LIGHT, "#fb8133": GOLD_DEEP,  # help disc (orange)
    "#ff4903": GOLD_LIGHT, "#df0b29": GOLD_DEEP,  # not-allowed (red)
}
# Gradient families whose shapes get the brown outline (the help disc doesn't).
OUTLINED_STOPS = {"#716ffb", "#4648fb", "#cd2ec5", "#21c4d6", "#ff4903", "#df0b29"}

# Help "?": height as a multiple of the disc radius, and upward shift from the
# disc center as a fraction of the radius. At 1.5x, raised 12%, it nearly
# touched the top of the disc and left a gap below.
HELP_GLYPH_SCALE = 1.3
HELP_GLYPH_RAISE = 0.0
HELP_GLYPH_WEIGHT = 0.55  # extra stroke (SVG units) to make the "?" bold
HELP_EMBOSS_OFFSET = 0.35  # light copy of the "?" shifted down-right (SVG units)

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

# --- SVG styling ----------------------------------------------------------------
def get_style(el: ET.Element) -> dict[str, str]:
    style = dict(kv.split(":", 1) for kv in (el.get("style") or "").split(";") if ":" in kv)
    for key in ("fill", "opacity", "filter", "stop-color"):
        if el.get(key) is not None:
            style.setdefault(key, el.get(key))
    return {k.strip(): v.strip() for k, v in style.items()}


def set_style(el: ET.Element, **props: str) -> None:
    style = get_style(el)
    for key, value in props.items():
        key = key.replace("_", "-")
        style[key] = value
        el.attrib.pop(key, None)
    el.set("style", ";".join(f"{k}:{v}" for k, v in style.items()))


def gradient_stops(root: ET.Element) -> dict[str, set[str]]:
    """Map each gradient id to the lowercase stop colors it resolves to."""
    grads = {g.get("id"): g for g in root.iter()
             if g.tag in (f"{{{SVG_NS}}}linearGradient", f"{{{SVG_NS}}}radialGradient")}
    def stops(gid: str, depth: int = 0) -> set[str]:
        g = grads.get(gid)
        if g is None or depth > 5:
            return set()
        own = {get_style(s).get("stop-color", "").lower() for s in g if s.tag == f"{{{SVG_NS}}}stop"}
        href = g.get(XLINK_HREF) or g.get("href")
        return own or (stops(href[1:], depth + 1) if href else set())
    return {gid: stops(gid) for gid in grads}


def goldify(svg_text: str, stem: str) -> str:
    """Apply the gold palette, outline and help-glyph tuning to an upstream SVG."""
    root = ET.fromstring(svg_text)
    stops_by_id = gradient_stops(root)
    for stop in root.iter(f"{{{SVG_NS}}}stop"):
        color = get_style(stop).get("stop-color", "").lower()
        if color in GRADIENT_STOPS:
            set_style(stop, stop_color=GRADIENT_STOPS[color])

    shapes = [el for el in root.iter() if el.tag.split("}")[1] in ("path", "circle", "rect", "ellipse")]
    for el in shapes:
        style = get_style(el)
        fill = style.get("fill", "")
        is_effect = "filter" in style  # shadows and glows
        if is_effect:
            continue
        if fill.startswith("url(#"):
            if stops_by_id.get(fill[5:-1], set()) & OUTLINED_STOPS:  # ids are case-sensitive
                set_style(el, stroke=OUTLINE, stroke_width=str(OUTLINE_WIDTH),
                          stroke_linejoin="round", paint_order="stroke")
        elif stem == "text":
            # The I-beam is a black outline path plus a near-black body.
            set_style(el, fill=OUTLINE if fill.lower() == "#000000" else GOLD_SOLID)
        elif stem == "help" and fill.lower() == "#ffffff":
            set_style(el, fill=OUTLINE)  # the "?" glyph

    if stem == "help":
        tune_help_glyph(root)
    return ET.tostring(root, encoding="unicode")


def tune_help_glyph(root: ET.Element) -> None:
    """Enlarge and re-center the "?" on the help disc; turn its shadow into a highlight."""
    by_id = {el.get("id"): el for el in root.iter() if el.get("id")}
    disc, glyph, shadow = by_id["circle12-0"], by_id["path28"], by_id["path898"]
    cx, cy, r = (float(disc.get(k)) for k in ("cx", "cy", "r"))
    bold = dict(stroke=OUTLINE, stroke_linejoin="round", paint_order="stroke")
    set_style(glyph, stroke_width=str(HELP_GLYPH_WEIGHT), **bold)

    # Measure the glyph's rendered bounds (including the bold stroke) with
    # everything else hidden.
    probe = ET.fromstring(ET.tostring(root))
    for el in probe.iter():
        if el.tag.split("}")[1] in ("path", "circle", "rect", "ellipse") and el.get("id") != "path28":
            set_style(el, display="none")
    scale_px = 16  # render at 16 px per unit for a precise box
    png = resvg_py.svg_to_bytes(svg_string=ET.tostring(probe, encoding="unicode"),
                                width=SVG_GRID * scale_px, height=SVG_GRID * scale_px)
    alpha = Image.open(io.BytesIO(bytes(png))).getchannel("A")
    x0, y0, x1, y1 = alpha.getbbox()
    # Center horizontally on the dot, not the whole box: the hook bulges to
    # the right, so a box-centered "?" had its stem and dot left of center.
    rows = [alpha.crop((0, y, alpha.width, y + 1)).getbbox() for y in range(y0, y1)]
    gap = max(i for i, row in enumerate(rows) if row is None)  # last empty row above the dot
    dx0, _, dx1, _ = alpha.crop((0, y0 + gap + 1, alpha.width, y1)).getbbox()
    gx, gy = (dx0 + dx1) / 2 / scale_px, (y0 + y1) / 2 / scale_px
    k = HELP_GLYPH_SCALE * r / ((y1 - y0) / scale_px)
    tx, ty = cx, cy - HELP_GLYPH_RAISE * r
    transform = f"translate({tx:.4f} {ty:.4f}) scale({k:.4f}) translate({-gx:.4f} {-gy:.4f})"
    glyph.set("transform", f"{transform} {glyph.get('transform', '')}".strip())
    # The stroke width is in the glyph's own coordinates, so undo the scale.
    set_style(glyph, stroke_width=f"{HELP_GLYPH_WEIGHT / k:.4f}")
    # Upstream's soft shadow becomes a light emboss offset down-right.
    emboss = f"translate({HELP_EMBOSS_OFFSET} {HELP_EMBOSS_OFFSET}) {transform}"
    shadow.set("transform", f"{emboss} {shadow.get('transform', '')}".strip())
    set_style(shadow, fill="#fff8dc", opacity="0.85", stroke="#fff8dc",
              stroke_width=f"{HELP_GLYPH_WEIGHT / k:.4f}", stroke_linejoin="round")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SVG_DIR.glob("*.svg"))
    for path in files:
        base = re.sub(r"-\d\d$", "", path.stem)     # animation frames are named like wait-01
        (OUT_DIR / path.name).write_text(goldify(path.read_text(encoding="utf-8"), base), encoding="utf-8")
    print(f"goldify: {len(files)} SVGs -> {OUT_DIR.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
