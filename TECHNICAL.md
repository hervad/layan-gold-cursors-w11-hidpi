# Technical notes

How the gold cursors are built, and the reasoning behind each choice.

## How Windows sizes cursors

At the default pointer size, Windows uses 32 px below 150% display scale, 48 px at 150–199%, 64 px at 200–299%, 96 px at 300–399% and 128 px from 400% ([Microsoft: Cursor Sizes](https://learn.microsoft.com/en-us/windows/win32/menurc/about-cursors#cursor-sizes)). The pointer-size slider multiplies that by 1, 1.5, 2 … 8 (`CursorBaseSize` 32–256). If a file contains the exact size, Windows uses it; otherwise it takes the next larger image and scales it down.

Earlier releases contained 32, 40, 48, 64, 96 and 128 px. Those were exact at the default pointer size, but 40 px is never requested, and larger pointer sizes had no 72, 144, 192 or 256 px images.

## Size ladders

| File type | Embedded sizes (px) |
| --- | --- |
| Static `.cur` | 32, 48, 64, 72, 96, 128, 144, 192, 256 |
| `working.ani` | 32, 48, 64, 96, 128, 256 |
| `busy.ani` | 32, 48, 64, 96, 128 |

On Windows 11, `LoadImage` silently returns `NULL` for an `.ani` whose frames contain too much image data. Frames of about 80 KB failed in our tests. `build.py` always includes 32–128 px for animations, then adds 256 and 192 px only if every frame stays under `ANI_FRAME_BUDGET` (56 KiB). The busy ring's glow and gradients compress poorly (its 256 px image alone is about 38 KB), so it stops at 128 px. On Windows, the build then loads every generated file with `LoadImageW` at every size and fails if any load returns `NULL`.

## Gold styling

The SVGs in `src/svg` are Layan's `svg` variant, unmodified. `goldify()` in `build.py` applies the style at build time:

| Upstream | Gold |
| --- | --- |
| Blue body gradient `#716FFB → #4648FB` | `#FFF0AB → #FFCD42`, with outline |
| Accent gradient `#CD2EC5 → #21C4D6` (bars, brackets, rings) | `#FFF0AB → #FFCD42`, with outline |
| Red not-allowed gradient | `#FFF0AB → #FFCD42`, with outline |
| Orange help disc | `#FFF0AB → #FFCD42`, no outline |
| Near-black I-beam | `#FFDF77` fill, `#392310` outline |
| White help "?" | `#392310`, bold, with a light emboss |

- **Outline:** a 1-unit `#392310` stroke painted under the fill (`paint-order: stroke`), so about half of it shows outside the shape. Shadows and glows are left as they are.
- **Help "?":** thickened with a 0.55-unit stroke, scaled so its height is 1.3 × the disc radius, and centered on the disc: vertically by its full height, horizontally by its dot, so the dot and stem sit on the disc's vertical axis (the hook bulges right, so centering the whole box pushed them left). Its bounds are measured from a render, so the glyph stays centered at every size. Upstream's soft shadow becomes a light copy offset down-right.

## Hotspots

The SVGs use a 32-unit grid, so one unit is one pixel at 32 px. Hotspots are mapped to `floor(coord × size / 32)`, the pixel that contains the point. Several of upstream's hotspots sat in empty space, so the pointer hotspots are measured at the visible tip:

| Cursor | Upstream | Now |
| --- | --- | --- |
| Arrow, help, working | 4, 4 | 4.78, 5.66 (drop tip) |
| Handwriting | 4, 29 | 2.56, 29.31 (pen tip) |
| Alternate | 16, 4 | 16, 4.5 (tip) |
| Link | 16, 4 | 13.78, 6.25 (fingertip) |

Everything else uses its center (16, 16).

## Installer

`build.py` generates `install.inf`, `uninstall.ps1` and `uninstall.cmd`:

- **Install** copies the files (and `install.inf` itself) to `%WINDIR%\Cursors\Layan Cursors (Gold)`, which needs administrator rights. It registers the scheme under `HKCU\Control Panel\Cursors\Schemes` and applies it to the current user. It then asks Windows to open Mouse Properties › Pointers, where clicking **OK** loads the cursors immediately. It also removes the scheme and files installed by earlier releases (*Layan Gold Cursors*).
- **Uninstall** resets the cursors to the Windows defaults, but only if Layan Gold is active, and reloads them with `SystemParametersInfo(SPI_SETCURSORS)`. It then runs the INF's `DefaultUninstall` section to delete the files and the scheme. The old `uninstall.bat` reset every cursor role even when another scheme was in use.

The release zip is written with fixed timestamps, so rebuilding from the same sources produces the same archive.
