# Technical notes

How the gold cursors are built, and the reasoning behind each choice.

## Build (since v3)

v3 is built by [w11-cursor-toolkit](https://github.com/hervad/w11-cursor-toolkit), the same toolchain as the other
`*-w11-hidpi` cursor themes, instead of this repo's own `build.py`:

1. `tools/goldify.py` writes gold SVGs from the unmodified upstream SVGs in `src/svg` to `build/gold`. Its styling code
   is v2's `goldify()` and `tune_help_glyph()`, moved without changes.
2. `w11cursor build theme.toml` renders every size with resvg (as v2 did), packs the `.cur`/`.ani` files and writes the
   installer; `w11cursor validate` re-reads every file.

**Equivalence with v2.0.1:** every cursor, every frame and every size present in both builds was compared - 347 images,
**0 hotspot differences and 0 pixel differences**.

## How Windows sizes cursors

Windows picks the image size as `CursorBaseSize × factor`, where `CursorBaseSize` is the pointer-size slider
(32, 48, 64 … 256) and the factor depends on the display scale: **1.0 from 100 % to 149 %, 1.5 from 150 % to 199 %**
(measured on Windows 11 25H2; see the toolkit's
[SIZE_POLICY.md](https://github.com/hervad/w11-cursor-toolkit/blob/main/docs/SIZE_POLICY.md)). Higher scales are
assumed to continue the pattern (2.0, 2.5, 3.0). If the file has that exact size Windows uses it; otherwise it resamples
the closest one. v2's table (×2 at 200 %, ×3 at 300 %, ×4 at 400 %, after Microsoft's documentation) was not measured.

## Size ladders

| File type | Embedded sizes (px) |
| --- | --- |
| Static `.cur` | 32, 48, 64, 72, 80, 96, 112, 120, 128, 144, 160, 168, 176, 192, 200, 208, 216, 224, 240, 256 |
| `working.ani`, `busy.ani` | 32, 48, 64, 72, 80, 96, 120, 128 |

Compared with v2: every v2 size is still there except `working.ani`'s 256 px; added are the sizes the measured rule
asks for (e.g. 80 px at pointer size 4, 72 and 120 px at 150 %).

**Animation limit (measured):** Windows refuses an `.ani` frame in which an image starts past byte 65,535 of the frame;
the total file size doesn't matter. With 144 px added, a busy frame would start an image at byte 71,832, so the
animations stop at 128 px (largest start: 55,743). The busy ring's glow and gradients compress poorly, so `busy.ani`
is about 1.6 MB.

## Gold styling

The SVGs in `src/svg` are Layan's `svg` variant, unmodified. `tools/goldify.py` applies the style:

| Upstream | Gold |
| --- | --- |
| Blue body gradient `#716FFB → #4648FB` | `#FFF0AB → #FFCD42`, with outline |
| Accent gradient `#CD2EC5 → #21C4D6` (bars, brackets, rings) | `#FFF0AB → #FFCD42`, with outline |
| Red not-allowed gradient | `#FFF0AB → #FFCD42`, with outline |
| Orange help disc | `#FFF0AB → #FFCD42`, no outline |
| Near-black I-beam | `#FFDF77` fill, `#392310` outline |
| White help "?" | `#392310`, bold, with a light emboss |

- **Outline:** a 1-unit `#392310` stroke painted under the fill (`paint-order: stroke`), so about half of it shows
  outside the shape. Shadows and glows are left as they are.
- **Help "?":** thickened with a 0.55-unit stroke, scaled so its height is 1.3 × the disc radius, and centered on the
  disc: vertically by its full height, horizontally by its dot, so the dot and stem sit on the disc's vertical axis.
  Its bounds are measured from a render, so the glyph stays centered at every size. Upstream's soft shadow becomes a
  light copy offset down-right.

## Hotspots

The SVGs use a 32-unit grid, so one unit is one pixel at 32 px. Hotspots are mapped to `floor(coord × size / 32)`, the
pixel that contains the point (`hotspot_mode = "pixel"` in `theme.toml`). Several of upstream's hotspots sat in empty
space, so the pointer hotspots are measured at the visible tip:

| Cursor | Upstream | Now |
| --- | --- | --- |
| Arrow, help, working | 4, 4 | 4.78, 5.66 (drop tip) |
| Handwriting | 4, 29 | 2.56, 29.31 (pen tip) |
| Alternate | 16, 4 | 16, 4.5 (tip) |
| Link | 16, 4 | 13.78, 6.25 (fingertip) |

Everything else uses its center (16, 16).

## Installer

The toolkit writes `install.inf` and `uninstall.cmd`. **Install** copies the files to
`%WINDIR%\Cursors\Layan Cursors (Gold)` (the same folder and scheme name as v2, so an upgrade replaces v2 in place),
registers the scheme under `HKCU\Control Panel\Cursors\Schemes`, applies it and opens Mouse Properties.
**Uninstall** removes the scheme entry and opens Mouse Properties; the folder is deleted by hand (README). v2's own
`DefaultUninstall` and its removal of the pre-v2 *Layan Gold Cursors* scheme are not part of v3.
