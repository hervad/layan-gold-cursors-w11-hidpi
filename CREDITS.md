# Credits

Layan Cursors (Gold) builds on several free cursor themes.

1. **[KDE Breeze](https://invent.kde.org/plasma/breeze)**: the original cursor design.
2. **[Capitaine Cursors](https://github.com/keeferrourke/capitaine-cursors)** by Keefer Rourke and contributors (LGPL-3.0-or-later), based on Breeze.
3. **[Layan cursors](https://github.com/vinceliuice/Layan-cursors)** by vinceliuice (GPL-3.0), based on Capitaine Cursors. All artwork in this project comes from Layan's `src/svg` at commit `b8c4689`, vendored unmodified in [`src/svg`](src/svg).
4. **[Layan cursors for Windows](https://github.com/emma-the-rock/Layan-cursors-for-Windows)** (GPL-3.0): the earlier Windows port, which chose which Layan shapes to use for each Windows role (for example, the corner shapes for diagonal resize). We use the same choices.

## This project

The gold edition is by [hervad](https://github.com/hervad):

- `tools/goldify.py` recolors Layan's gradients to gold, adds the brown outline, and enlarges and embosses the help "?"
- [w11-cursor-toolkit](https://github.com/hervad/w11-cursor-toolkit) (since v3) renders every cursor at the sizes Windows
  requests, from 32 to 256 px, and generates the installer
- Pointer hotspots are measured at each shape's tip
- Location and person select (new in v3) use the pointing hand

## License

Distributed under the **GNU General Public License v3.0**, the license of Layan cursors. See [LICENSE](LICENSE). The SVG sources, `tools/goldify.py` and `theme.toml` are included, so everything can be rebuilt and modified.
