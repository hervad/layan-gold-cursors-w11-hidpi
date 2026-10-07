#!/usr/bin/env python3
"""Build the Layan Gold Windows cursor scheme from the SVG sources in src/svg.

Usage:
    python -m pip install -r requirements.txt
    python build.py

Writes layan-gold/, layan-gold-cursors-windows.zip and docs/preview.png.
On Windows, every generated file is also test-loaded with the system loader.
The SVGs are vendored unmodified from vinceliuice/Layan-cursors (commit
b8c4689, "svg" variant); the gold style is applied here at build time.
"""

from __future__ import annotations

import io
import math
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import resvg_py
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SVG_DIR = ROOT / "src" / "svg"
OUT_DIR = ROOT / "layan-gold"
ZIP_PATH = ROOT / "layan-gold-cursors-windows.zip"
PREVIEW_PATH = ROOT / "docs" / "preview.png"

SCHEME_NAME = "Layan Cursors (Gold)"
LEGACY_SCHEME = "Layan Gold Cursors"  # name used by releases before v2

# The SVGs are drawn on a 32-unit grid, the same as Windows' nominal 32 px.
SVG_GRID = 32

# Windows picks the cursor size in steps from the display scale -- 32 (<150%),
# 48 (150-199%), 64 (200-299%), 96 (300-399%), 128 (>=400%) -- and multiplies
# it by the pointer-size slider (CursorBaseSize / 32 = 1, 1.5, 2, ... 8).
# It uses an exact match when present and otherwise shrinks the next larger
# image. Static cursors carry every size needed for slider positions 1-3.
STATIC_SIZES = (32, 48, 64, 72, 96, 128, 144, 192, 256)
# Windows silently refuses .ani files whose frames carry too much image data
# (observed around 79 KB per frame on Windows 11). Animated cursors always get
# the default-slider sizes, then each optional size in turn while every frame
# stays under this budget.
ANIMATED_SIZES = (32, 48, 64, 96, 128)
ANIMATED_OPTIONAL_SIZES = (256, 192)
ANI_FRAME_BUDGET = 56 * 1024

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

# Windows cursor roles in the order the registry scheme string expects:
# (role, output file, source SVG stem, hotspot in SVG units, frames).
# Pointer hotspots are measured at the visible tip; upstream's config puts
# several of them in empty space next to it. Pin and Person have no Layan
# equivalent and are left empty.
DROP_TIP = (4.78, 5.66)
ROLES = (
    ("Arrow", "arrow.cur", "default", DROP_TIP, 0),
    ("Help", "help.cur", "help", DROP_TIP, 0),
    ("AppStarting", "working.ani", "progress", DROP_TIP, 23),
    ("Wait", "busy.ani", "wait", (16, 16), 23),
    ("Crosshair", "crosshair.cur", "crosshair", (16, 16), 0),
    ("IBeam", "text.cur", "text", (16, 16), 0),
    ("NWPen", "pen.cur", "pencil", (2.56, 29.31), 0),
    ("No", "unavailable.cur", "not-allowed", (16, 16), 0),
    ("SizeNS", "size_ns.cur", "row-resize", (16, 16), 0),
    ("SizeWE", "size_ew.cur", "col-resize", (16, 16), 0),
    ("SizeNWSE", "size_nwse.cur", "bottom_right_corner", (16, 16), 0),
    ("SizeNESW", "size_nesw.cur", "bottom_left_corner", (16, 16), 0),
    ("SizeAll", "move.cur", "all-scroll", (16, 16), 0),
    ("UpArrow", "up_arrow.cur", "up-arrow", (16, 4.5), 0),
    ("Hand", "link.cur", "pointer", (13.78, 6.25), 0),
)
EMPTY_ROLES = 2  # Pin, Person

# Frame duration in jiffies (1/60 s): 23 frames x 33 ms, matching upstream's
# 30 ms per frame.
ANI_JIFFIES = 2
ANI_TITLE = "Layan Cursors (Gold)"
ANI_ARTIST = "vinceliuice; gold edition by hervad"

ZIP_EXTRAS = ("LICENSE", "CREDITS.md")
ZIP_DATE = (2026, 1, 1, 0, 0, 0)  # fixed so the archive is reproducible

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


def render(svg_text: str, size: int) -> bytes:
    """Render SVG markup to an optimized 32-bit RGBA PNG of size x size pixels."""
    png = bytes(resvg_py.svg_to_bytes(svg_string=svg_text, width=size, height=size))
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    if image.size != (size, size):
        raise ValueError(f"rendered at {image.size}, expected {size}")
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def source(stem: str) -> str:
    """Load an upstream SVG (animation frames are named like wait-01) and goldify it."""
    base = re.sub(r"-\d\d$", "", stem)
    return goldify((SVG_DIR / f"{stem}.svg").read_text(encoding="utf-8"), base)


# --- Cursor files -----------------------------------------------------------------
def scale_hotspot(hotspot: tuple[float, float], size: int) -> tuple[int, int]:
    """Map a hotspot from SVG units to the pixel that contains it."""
    return tuple(min(size - 1, math.floor(c * size / SVG_GRID)) for c in hotspot)


def build_cur(svg_text: str, hotspot: tuple[float, float], sizes: tuple[int, ...]) -> bytes:
    """Build a multi-resolution .cur file with one PNG image per size."""
    return pack_cur([(size, render(svg_text, size)) for size in sizes], hotspot)


def pack_cur(images: list[tuple[int, bytes]], hotspot: tuple[float, float]) -> bytes:
    """Pack (size, PNG) images into a .cur file."""
    header = struct.pack("<HHH", 0, 2, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = [], []
    for size, png in images:
        hx, hy = scale_hotspot(hotspot, size)
        dim = size % 256  # 0 means 256 in the directory entry
        entries.append(struct.pack("<BBBBHHII", dim, dim, 0, 0, hx, hy, len(png), offset))
        blobs.append(png)
        offset += len(png)
    return header + b"".join(entries) + b"".join(blobs)


def riff_chunk(chunk_id: bytes, data: bytes) -> bytes:
    pad = b"\0" if len(data) % 2 else b""
    return chunk_id + struct.pack("<I", len(data)) + data + pad


def riff_list(list_type: bytes, chunks: list[bytes]) -> bytes:
    return riff_chunk(b"LIST", list_type + b"".join(chunks))


def build_ani(frames: list[bytes]) -> bytes:
    """Build an .ani file whose frames are multi-resolution .cur images."""
    info = riff_list(b"INFO", [
        riff_chunk(b"INAM", ANI_TITLE.encode("ascii") + b"\0"),
        riff_chunk(b"IART", ANI_ARTIST.encode("ascii") + b"\0"),
    ])
    # cbSize, nFrames, nSteps, cx, cy, cBitCount, cPlanes, JifRate, flags (AF_ICON)
    anih = riff_chunk(b"anih", struct.pack("<9I", 36, len(frames), len(frames),
                                           0, 0, 32, 1, ANI_JIFFIES, 1))
    fram = riff_list(b"fram", [riff_chunk(b"icon", f) for f in frames])
    body = b"ACON" + info + anih + fram
    return b"RIFF" + struct.pack("<I", len(body)) + body


def build_inf() -> str:
    files = [role[1] for role in ROLES]
    paths = ",".join(f"%10%\\%CUR_DIR%\\{f}" for f in files) + "," * EMPTY_ROLES
    apply_roles = [f'HKCU,"Control Panel\\Cursors",{role},0x00020000,"%10%\\%CUR_DIR%\\{f}"'
                   for role, f, *_ in ROLES]
    lines = [
        f"; {SCHEME_NAME}",
        '; Right-click this file and select "Install" (asks for administrator rights).',
        "; The scheme is applied for the current user and Mouse Properties opens;",
        "; click OK there to load the new cursors.",
        "; Uninstall: run uninstall.cmd as administrator.",
        "",
        "[Version]",
        'Signature = "$Windows NT$"',
        "",
        "[DefaultInstall]",
        "CopyFiles = Scheme.Cur, Scheme.Inf",
        "DelFiles  = Legacy.Cur",
        "DelReg    = Legacy.Reg",
        "AddReg    = Scheme.Reg, Apply.Reg",
        "",
        "[DefaultUninstall]",
        "DelFiles  = Scheme.Cur, Scheme.Inf",
        "DelReg    = Scheme.DelReg",
        "",
        "[DestinationDirs]",
        'Scheme.Cur = 10,"%CUR_DIR%"',
        'Scheme.Inf = 10,"%CUR_DIR%"',
        'Legacy.Cur = 10,"%LEGACY_DIR%"',
        "",
        "[Scheme.Reg]",
        f'HKCU,"Control Panel\\Cursors\\Schemes","%SCHEME_NAME%",,"{paths}"',
        "",
        "[Apply.Reg]",
        'HKCU,"Control Panel\\Cursors",,0x00020000,"%SCHEME_NAME%"',
        'HKCU,"Control Panel\\Cursors","Scheme Source",0x00010001,1',
        *apply_roles,
        "; Open Mouse Properties > Pointers so the user can confirm with OK.",
        'HKLM,"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce\\Setup\\","",,'
        '"rundll32.exe shell32.dll,Control_RunDLL main.cpl @0,1"',
        "",
        "[Scheme.DelReg]",
        'HKCU,"Control Panel\\Cursors\\Schemes","%SCHEME_NAME%"',
        "",
        "[Legacy.Reg]",
        'HKCU,"Control Panel\\Cursors\\Schemes","%LEGACY_SCHEME%"',
        "",
        "[Scheme.Cur]",
        *files,
        "",
        "[Scheme.Inf]",
        "install.inf",
        "",
        "[Legacy.Cur]",
        *LEGACY_FILES,
        "",
        "[Strings]",
        f'CUR_DIR       = "Cursors\\{SCHEME_NAME}"',
        f'SCHEME_NAME   = "{SCHEME_NAME}"',
        f'LEGACY_DIR    = "Cursors\\{LEGACY_SCHEME}"',
        f'LEGACY_SCHEME = "{LEGACY_SCHEME}"',
    ]
    return "\r\n".join(lines) + "\r\n"


# Files installed by releases before v2, removed on upgrade.
LEGACY_FILES = (
    "Install.inf", "crosshair.cur", "default.cur", "help.cur", "not-allowed.cur",
    "pencil.cur", "pointer.cur", "progress.ani", "size_all.cur", "size_bdiag.cur",
    "size_fdiag.cur", "size_hor.cur", "size_ver.cur", "text.cur", "up-arrow.cur", "watch.ani",
)


UNINSTALL_PS1 = r"""# Uninstalls @SCHEME@. If the scheme is active, switches back to the Windows
# default cursors first, then removes the installed files and the scheme entry.
$ErrorActionPreference = 'Stop'
$scheme = '@SCHEME@'

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$key = 'HKCU:\Control Panel\Cursors'
if ((Get-ItemProperty $key).'(default)' -eq $scheme) {
    foreach ($role in @ROLES@) {
        Set-ItemProperty $key $role ''
    }
    Set-ItemProperty $key '(default)' 'Windows Default'
    $api = Add-Type -PassThru -Name Cursors -Namespace Win32 -MemberDefinition @'
[DllImport("user32.dll")]
public static extern bool SystemParametersInfo(uint action, uint param, System.IntPtr value, uint flags);
'@
    [void]$api::SystemParametersInfo(0x57, 0, [IntPtr]::Zero, 3)  # SPI_SETCURSORS: reload now
}

$inf = Join-Path $PSScriptRoot 'install.inf'
Start-Process rundll32.exe -Wait -ArgumentList "setupapi.dll,InstallHinfSection DefaultUninstall 132 $inf"
Write-Host "$scheme has been removed."
Read-Host 'Press Enter to close'
"""

UNINSTALL_CMD = """@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
"""


def build_uninstaller() -> dict[str, bytes]:
    roles = ", ".join(f"'{role}'" for role, *_ in ROLES)
    ps1 = UNINSTALL_PS1.replace("@SCHEME@", SCHEME_NAME).replace("@ROLES@", roles)
    crlf = lambda text: text.replace("\n", "\r\n").encode("ascii")
    return {"uninstall.ps1": crlf(ps1), "uninstall.cmd": crlf(UNINSTALL_CMD)}


# --- Verification -------------------------------------------------------------------
def verify_cur(data: bytes, hotspot: tuple[float, float], sizes: tuple[int, ...], label: str) -> None:
    """Re-parse a generated .cur and check every directory entry against its image."""
    def check(ok: bool, problem: str) -> None:
        if not ok:
            raise ValueError(f"{label}: {problem}")

    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    check((reserved, kind, count) == (0, 2, len(sizes)), f"bad header {reserved, kind, count}")
    for i, size in enumerate(sizes):
        w, h, _, _, hx, hy, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        image = Image.open(io.BytesIO(data[offset:offset + length]))
        check((w or 256, h or 256) == (size, size), f"directory says {w}x{h}, expected {size}")
        check(image.size == (size, size) and image.mode == "RGBA",
              f"image is {image.size} {image.mode}, expected {size}px RGBA")
        check((hx, hy) == scale_hotspot(hotspot, size), f"wrong hotspot at {size}px")


def verify_with_windows(paths: list[Path]) -> None:
    """Load every file with the Windows cursor loader at each target size."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.DestroyCursor.argtypes = (wintypes.HANDLE,)
    IMAGE_CURSOR, LR_LOADFROMFILE = 2, 0x10
    for path in paths:
        for size in STATIC_SIZES:
            handle = user32.LoadImageW(None, str(path), IMAGE_CURSOR, size, size, LR_LOADFROMFILE)
            if not handle:
                raise RuntimeError(f"Windows failed to load {path.relative_to(ROOT)} at {size}px")
            user32.DestroyCursor(handle)


# --- Outputs ----------------------------------------------------------------------------
def write_preview() -> None:
    """Draw every cursor at 48 px on light and dark panels, doubled for HiDPI screens."""
    size, gap, pad, scale = 48, 20, 28, 2
    panels = ((243, 243, 243), (32, 32, 32))
    width = pad * 2 + len(ROLES) * size + (len(ROLES) - 1) * gap
    height = len(panels) * (size + pad * 2)
    canvas = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    icons = [Image.open(io.BytesIO(render(source(f"{stem}-01" if frames else stem), size * scale)))
             for _, _, stem, _, frames in ROLES]
    for row, background in enumerate(panels):
        top = row * (size + pad * 2) * scale
        corners = (row == 0, row == 0, row == len(panels) - 1, row == len(panels) - 1)
        draw.rounded_rectangle((0, top, width * scale - 1, top + (size + pad * 2) * scale - 1),
                               radius=16 * scale, fill=background, corners=corners)
        for col, icon in enumerate(icons):
            canvas.alpha_composite(icon, ((pad + col * (size + gap)) * scale, top + pad * scale))
    PREVIEW_PATH.parent.mkdir(exist_ok=True)
    canvas.save(PREVIEW_PATH, optimize=True)


def build_cursors() -> dict[str, bytes]:
    outputs = {}
    for _, filename, stem, hotspot, frames in ROLES:
        print(f"  {filename}", flush=True)
        if frames:
            svgs = [source(f"{stem}-{i:02d}") for i in range(1, frames + 1)]
            candidates = ANIMATED_SIZES + ANIMATED_OPTIONAL_SIZES
            pngs = [{size: render(svg, size) for size in candidates} for svg in svgs]
            sizes = ANIMATED_SIZES
            for extra in ANIMATED_OPTIONAL_SIZES:
                trial = tuple(sorted(sizes + (extra,)))
                if all(len(pack_cur([(s, p[s]) for s in trial], hotspot)) <= ANI_FRAME_BUDGET
                       for p in pngs):
                    sizes = trial
            curs = []
            for i, p in enumerate(pngs, 1):
                cur = pack_cur([(s, p[s]) for s in sizes], hotspot)
                verify_cur(cur, hotspot, sizes, f"{filename} frame {i}")
                if len(cur) > ANI_FRAME_BUDGET:
                    raise RuntimeError(f"{filename} frame {i} is {len(cur)} bytes, "
                                       f"over the {ANI_FRAME_BUDGET}-byte budget")
                curs.append(cur)
            print(f"    sizes: {', '.join(map(str, sizes))}")
            outputs[filename] = build_ani(curs)
        else:
            cur = build_cur(source(stem), hotspot, STATIC_SIZES)
            verify_cur(cur, hotspot, STATIC_SIZES, filename)
            outputs[filename] = cur
    outputs["install.inf"] = build_inf().encode("ascii")
    outputs.update(build_uninstaller())
    return outputs


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    archive, cursor_files = [], []
    for filename, data in build_cursors().items():
        (OUT_DIR / filename).write_bytes(data)
        archive.append((f"{OUT_DIR.name}/{filename}", data))
        if filename.endswith((".cur", ".ani")):
            cursor_files.append(OUT_DIR / filename)
    # Text files go in with CRLF line endings so they read well in Notepad.
    for name in ZIP_EXTRAS:
        text = (ROOT / name).read_text(encoding="utf-8")  # universal newlines -> "\n"
        archive.append((name, text.replace("\n", "\r\n").encode("utf-8")))

    if sys.platform == "win32":
        verify_with_windows(cursor_files)
        print(f"Windows loaded all {len(cursor_files)} cursors at every size")

    with zipfile.ZipFile(ZIP_PATH, "w") as zf:
        for name, data in sorted(archive):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.external_attr = 0o644 << 16  # rw-r--r-- when extracted on Unix
            zf.writestr(info, data, zipfile.ZIP_DEFLATED, compresslevel=9)
    print(f"Wrote {ZIP_PATH.name} ({ZIP_PATH.stat().st_size / 1e6:.1f} MB)")
    write_preview()
    print(f"Wrote {PREVIEW_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
