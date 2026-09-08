# Changelog

## 1.3.1

- Removed automatic first-image thumbnails from compact Codex navigation. Sidebar navigation is now clean, text-first, and never shows arbitrary action-symbol or decorative-image crops.
- Table-of-contents artwork is now deliberate: choose an image in Codex Studio, or explicitly click **Use first entry image**. Nothing is auto-promoted anymore.
- Manually selected entry TOC artwork is rendered as a subtle full-row backdrop in the main Codex instead of a tiny square icon; chapter artwork and large featured cards remain intact.
- Improved Build Doctor wording so engine/cache adjustments are not described as a successful recovery when the underlying LaTeX source still contains errors.
- Added source excerpts directly beneath clickable compile diagnostics and targeted explanations for `geometry` option clashes, stray `\\` line breaks, invalid dimensions, and mismatched environments. These diagnostics are read-only and never rewrite the campaign source.


## 1.3.0

- Fixed `fontspec` projects being sent to pdfLaTeX. Loreforge now detects `fontspec`, `\setmainfont`, `\setsansfont`, `\setmonofont`, `unicode-math`, and Lua-only source across `.tex`, `.sty`, and `.cls` files and automatically selects XeLaTeX/LuaLaTeX even when an older Railway environment still says `LATEX_ENGINE=pdflatex`.
- When the effective engine changes, Loreforge clears only generated dependency/auxiliary state before compiling so stale pdfLaTeX `.fdb_latexmk` data cannot poison the first XeLaTeX build.
- Added OpenType TeX Gyre and EB Garamond system fonts plus fontconfig to the Docker image. The Docker build now validates that **TeX Gyre Adventor** and **EB Garamond** are actually discoverable before the image succeeds.
- Improved Build Doctor so the `fontspec + pdfTeX` failure is identified as an engine mismatch rather than incorrectly reported as a missing font. The build panel now shows the effective engine on both successful and failed builds.
- Added first-class player-Codex rendering for the supplied PF2e campaign macros: `\feat`, `\action`, `\itemtemplate`, `monster`, `\monstersection`, `\monsterline`, `\monsterabilityscores`, `\monsterdefenses`, `\monsterspeed`, `\monsterattack`, `\monsterspellcasting`, and `\monsterability`.
- Added native inline rendering for `\actionOne`, `\actionTwo`, `\actionThree`, `\reaction`, and `\freeAction`, using the project's `Images/Symbols/` art where available and a readable fallback otherwise.
- Added native handling for the legacy `\image{width}{path}` helper and retained `\pon` / `\chaptergroup` semantics for entity pages and navigation grouping.
- Replaced fragile regex-only custom-macro argument parsing with balanced-brace parsing for up to eight arguments, so nested formatting in long feat/action/item/stat-block descriptions is preserved.
- Added a **PF2e** insert menu to the GM editor with ready-to-fill feat, action, item, monster, stat-line, and action-symbol snippets.
- Added regression tests for automatic XeLaTeX switching, persistent stale-engine cleanup, PF2e semantic cards/stat blocks, action symbols, legacy image helpers, and chapter-group navigation.

## 1.2.0

- Added Codex Studio art direction for table-of-contents covers/thumbnails, entry heroes, full-page backgrounds, focal points, article layouts, featured entries, and public/teaser/hidden discovery states.
- Added automatic TOC artwork fallback from the first image already present in an entry; manual art always overrides it.
- Added the editor **Artwork** composer with center/left/right/wide/breakout/full-bleed/portrait/banner/edge/watermark layouts, opacity, focus, blend modes, frames, captions, and parallax while preserving ordinary LaTeX figures for PDF/Overleaf.
- Added **Scene** panels: web-only atmospheric background wrappers around selected normal LaTeX prose, with tone, focus, strength, height, and parallax controls.
- Added conservative automatic cross-linking of unique codex names, related lore, backlinks, and a player-facing pan/zoom **Lore Network** graph.
- Added heading permalinks and an On-this-page scroll-spy navigator for long entries.
- Fixed the player codex sidebar resetting on entry navigation by preserving open groups, scroll position, and clicked-row viewport position across page loads.
- Added player-side bookmark/recent-reading trail and copyable page links.
- Added quick Open player page / Copy link controls to Codex Studio.
- Added **Build Doctor** recovery for stale `latexmk` failed-build caches, automatic auxiliary-state repair, direct-engine diagnostic fallback, and actionable compile suggestions. This specifically addresses the `Nothing to do for main.tex` + `pdflatex: gave an error` failure mode.
- Added regression tests for scene panels, automatic TOC imagery, automatic links/backlinks, and stale-latexmk diagnosis.

## 1.1.0

- Fixed responsive conversion of `longtable`, `tabular`, `tabularx`, and `tabulary`, including complex paragraph-column declarations.
- Added first-class `\pon{...}` Person-of-Note article grouping, Profile metadata grids, and TikZ-overlay portrait handling.
- Improved `\includegraphics` layout, asset lookup, captions, portrait/landscape/panorama inference, and image lightbox viewing.
- Made map `cover + edge lock` the strict default for both player and GM map cameras so empty space cannot be panned into view.
- Reworked marker authoring with an explicit placement crosshair, searchable marker directory, click-to-focus behavior, and removed accidental double-click placement.
- Added a searchable player location list alongside marker-category filters.
- Expanded the fantasy atmosphere system to 38 toggleable options and 16 presets, including god rays, valley mist, blizzards, heat haze, wave crests, shooting stars, petals, bats, dragon shadows, spectral wisps, cursed miasma, rune pulses, spores, blood moon, and fogged edges.
- Retains the v1.0.1 low-disk-space ZIP import fix.
