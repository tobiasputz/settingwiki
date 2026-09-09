# Loreforge — LaTeX-first interactive campaign wiki

Loreforge turns a normal multi-file LaTeX campaign project into **two synchronized views of the same setting**:

1. an Overleaf-style GM authoring workspace with a source tree, LaTeX editor, autosave, revision history, build log and live PDF preview; and
2. a polished player-facing interactive setting wiki with full-text search, automatic chapter/section navigation and interactive maps.

It is designed for long-running Pathfinder 2e / TTRPG campaigns where the LaTeX project is already the canonical campaign document and manually re-uploading a PDF has become annoying.

## What it does

- **Edit LaTeX in the browser.** `/admin` is a private GM workspace.
- **Live formatting feedback.** Saving updates the player-wiki preview; after a short idle delay Loreforge compiles the real LaTeX project and refreshes the PDF preview.
- **Import your existing Overleaf project.** Upload the Overleaf source ZIP from the Project tab. Loreforge backs up the existing project first.
- **Keep your Overleaf workflow if you want it.** Export the entire current project as a ZIP at any time and upload it to Overleaf again.
- **Understands project structure.** It detects the likely main `.tex` file, resolves `\input{}` / `\include{}`, preserves chapters/sections/subsections, inspects `\newcommand`, custom environments, packages, colors, and `\includegraphics` references.
- **Fails gracefully on unusual LaTeX.** Unknown commands are unwrapped so their human-readable arguments are not silently discarded. Custom macros whose names look like NPC/location/lore-box commands are rendered as callouts in the wiki. `\pon{...}` is treated specially as a Person-of-Note article root, so its Profile/Biography subsections stay together instead of becoming unrelated wiki pages.
- **Understands campaign-book layouts.** `longtable`, `tabular`, `tabularx` and `tabulary` are converted to responsive HTML tables without leaking TeX column declarations such as `>{\raggedright}p{3.5cm}` into player text. `multicols` profile blocks become compact metadata grids.
- **Smart imported images.** `\includegraphics` assets are resolved even when extensions are omitted or assets live below graphics folders. Figure/wrapfigure layouts, PDF graphics, captions and common TikZ page-overlay portraits are translated to web-friendly layouts. Players can click rendered images for a full-resolution lightbox, and portrait/landscape/panorama treatment is inferred from the actual image dimensions.
- **Compiles the original PDF.** The Docker image includes `latexmk`, pdfLaTeX, XeLaTeX, LuaLaTeX, common LaTeX-extra packages, fonts and graphics packages. Project-local `.cls` and `.sty` files work normally.
- **Codex Studio / art direction.** Every chapter and entry can have its own table-of-contents artwork. Entries can additionally have a cinematic hero, full-page background, focal point, background strength, article width, feature status, and public/teaser/hidden discovery state. By default, the first meaningful image found inside a chapter becomes the darkened atmospheric background of the **whole large chapter/section block** in the Codex. Individual entry headlines and the article sidebar remain clean and text-only. Deliberate chapter artwork overrides the automatic image, and the automatic section backgrounds can be switched off globally in Project settings.
- **Free-form web artwork without giving up LaTeX.** The **Artwork** tool inserts an ordinary `\includegraphics` figure for the PDF plus a harmless `% loreforge-image:` comment for the wiki. Layouts include centered, floating left/right, wide, breakout, full-bleed, portrait, banner, decorative edge art, and watermark, with independent width, opacity, crop focus, blend mode, frame, caption, and parallax controls. Existing automatic image handling still works when you do not add a directive.
- **Atmospheric scene panels.** Select any normal LaTeX prose and press **Scene** to place that passage over an image in the player wiki. The source remains valid ordinary LaTeX because Loreforge stores the web presentation as comments around the selected text. Scene tones include dark, light, sepia, arcane, mist, and blood, with focus, image strength, height, and optional parallax.
- **Living lore connections.** Unique codex names mentioned naturally in prose can be cross-linked automatically (optional in Project settings), explicit `\wiki{}` links remain supported, and pages show related lore/backlinks. The **Lore Network** player view turns these relationships into a pan/zoom interactive graph with artwork-backed nodes.
- **Long-entry navigation.** Section/subsection headings receive stable deep links and long articles get an **On this page** navigator with scroll tracking. Player bookmarks/recently viewed entries form a private browser-side reading trail.
- **Stable codex sidebar.** Opening another entry no longer throws the player back to the top of the navigation. Loreforge remembers expanded chapter groups, scroll position, and the clicked row position across full page navigation.
- **Build Doctor.** `latexmk` stale-failure states are detected and repaired automatically, the underlying TeX engine is invoked for a diagnostic pass when `latexmk` only returns a wrapper summary, and the editor surfaces likely fixes rather than only showing `pdflatex: gave an error`. High-confidence source mistakes can be repaired individually or with **Apply all safe fixes**; the full batch is verified before any source is changed and every affected file is revision-backed. Repeated `geometry` package declarations can be consolidated automatically. When TeX returns errors but still creates a fresh PDF, Loreforge keeps that recoverable preview visible while clearly marking the build as not clean.
- **Native PF2e campaign mechanics.** Your existing `\feat`, `\action`, `\itemtemplate`, creature/stat-block commands, action-symbol macros, `\chaptergroup`, `\pon`, and legacy `\image` helper remain authoritative LaTeX for the PDF while receiving dedicated responsive Codex rendering. Nested arguments are parsed safely, and the editor has a PF2e insertion palette for creating new entries with the same command vocabulary.
- **Interactive atlas.** Upload a map image, enter explicit **＋ Location** placement mode, follow the placement crosshair, click once to place a marker, drag markers into position, attach descriptions and link them to codex pages. A searchable marker directory makes existing locations easy to find/focus. Player maps also expose a searchable location panel and category filters. Markers can be player-visible or GM-only and use distinct symbols for cities, ports, ruins, danger, secrets, temples, portals, quests, and more.
- **Edge-locked map navigation.** Player maps use a cover-style minimum zoom by default: when you pan, the map cannot be pushed past the viewport and reveal empty space beyond its edges. Wheel, buttons, and touch pinch all zoom around the pointer/fingers.
- **Fantasy atmosphere studio.** Per-map switches include moving clouds, cloud shadows, rolling fog, valley mist, god rays, rain, lightning, snow, blizzards, ashfall, sand/dust, heat haze, ocean shimmer, moving wave crests, embers, fireflies, pollen, leaves, petals, birds, bats, rare dragon shadows, arcane motes, spectral wisps, cursed miasma, ley lines, rune pulses, glowing spores, aurora, stars, shooting stars, vignette, fogged edges, parchment warmth, moonlight, blood-moon tint, cartographer grid, and compass rose. Presets now include Calm Fantasy, Stormbound, Frozen North, Haunted Realm, Arcane Night, Volcanic Wastes, Ancient Parchment, Coastal Breeze, Autumn Road, Feywild Glade, Scorched Desert, Underdark, Blood Moon, Ancient Ruins, Blighted Realm, and High Fantasy.
- **Revision safety.** Loreforge keeps up to 40 saved revisions of each file edited in the browser.
- **Personal player invitations.** Player access is invitation-only by default. **Admin → Access** creates one signed link per player; each link can be copied, expired, revoked, restored, rotated, device-limited, or have its remembered devices reset independently. Legacy shared-password and public modes remain available, while the editor continues to use `ADMIN_PASSWORD`.
- **Read → edit source bridge.** When you browse the player Codex while logged in as GM, a persistent **Edit source** control opens the exact LaTeX file/line in Campaign Studio. On long Person-of-Note pages it follows the section currently being read, and the editor offers **Back to entry** after the correction.

## Loreforge 2: run the campaign from the wiki

Loreforge 2 adds a campaign-runtime layer on top of the LaTeX/PDF workflow rather than replacing it. The canonical source remains ordinary LaTeX, while the live site can now change what each invited player knows and what the table is currently focused on.

- **GM Session Mode:** start/end sessions, spotlight relevant lore and maps, reveal secrets, send discoveries, and surface handouts from a touch-friendly session dashboard.
- **Player Session Mode:** a phone-first table screen with current location, spotlight lore, live discoveries, open mysteries, handouts, and previous-session recaps.
- **Progressive lore:** select prose in the editor and press **Reveal** to create a web-only hidden/rumor/discovered/public block. Audience and expiry controls live in Campaign Control / GM Session Mode.
- **Timeline + world calendar:** maintain eras, wars, reigns, discoveries, festivals, custom months/weekdays/moons, seasons, and the current in-world date.
- **Mystery boards:** pin clues and connect them with editable red-string relationships. Player boards render only clues and connections the player is allowed to know.
- **Relationships and dossiers:** explicit `member of`, `worships`, `located in`, `enemy of`, etc. relationships feed profiles, backlinks, hover previews and the Lore Network; aliases redirect alternate names to the canonical entry.
- **Notes and reading history:** players can keep private/party notes and bookmarks while the GM can keep private margin notes. Recent-reading and newly-discovered feeds help players return after a session.
- **Handouts:** letters, parchment documents, newspapers, wanted posters, journals and visions can be delivered independently or attached to a session.
- **Atlas layers + discovery fog:** overlay political/road/trade/religion/etc. layers, reveal regions as the party explores, and estimate map travel between discovered markers.
- **Campaign Control:** health checks, snapshots/restore, templates, world settings, lore styling, session history and campaign state live in one GM workspace.
- **Phone/iPad/PWA:** the player site has a bottom-tab mobile UI, touch Atlas controls and responsive reading/session layouts. The GM editor becomes Files / Editor / Preview panes on small screens. iPhone/iPad: Safari → Share → **Add to Home Screen**. Android/Chrome: **Install app** / Add to Home Screen.

The editor's top application bar is persistent while working in long files, and the GM can still jump from a typo in the player Codex directly to the exact `.tex` source line and back.

## Repository layout

```text
pf2e-loreforge/
├─ app/                 FastAPI backend, LaTeX parsing, compilation, maps, storage
├─ campaign/            first-run seed project; replace/import from the editor
├─ static/              editor, wiki, and animated-map frontend
├─ templates/           player and admin HTML
├─ tests/               parser/storage regression tests
├─ Dockerfile           Railway/local production image
├─ railway.toml         health check + Docker build config
└─ requirements.txt
```

## Railway deployment

### 1. Push this repository to GitHub

Create a normal GitHub repository from this folder and push it.

### 2. Create the Railway service

In Railway, create a service from the GitHub repo. The root `Dockerfile` is detected automatically. The service listens on Railway's injected `$PORT` and exposes `/health` as its health check.

### 3. **Attach a persistent volume at `/data`**

This is the important step for wiki-first authoring. Your editable LaTeX project, revision history, compiled artifacts, maps and SQLite metadata live under `/data`.

Without a volume the app still runs, but browser edits live on the service's ephemeral filesystem and can disappear on a redeploy.

### 4. Set variables

At minimum:

```text
ADMIN_PASSWORD=<a strong GM password>
```

Optional:

```text
# Only needed if you deliberately switch Admin → Access to Shared Password mode:
PLAYER_PASSWORD=<legacy shared player password>
LATEX_ENGINE=auto           # recommended; also accepts pdflatex / xelatex / lualatex
LATEX_TIMEOUT=60
LATEX_ALLOW_SHELL_ESCAPE=0
```

The default player gate is **Invitation links only**, so normal deployments do not need `PLAYER_PASSWORD`. After logging into `/admin`, open **Access**, create one invitation for each player, and send each player their own link.

If `ADMIN_PASSWORD` is omitted, Loreforge generates one on first startup, stores it in `/data/.admin_password`, and prints it to the service logs. Setting the variable explicitly is cleaner.

### 5. Open `/admin`

Import the ZIP downloaded from **Overleaf → Download → Source**, or simply start editing the included sample project.

GitHub remains the deployment source for the *application*. Your live campaign source is persistent data inside Loreforge, so updating the application does not require manually copying the campaign PDF anywhere.

## Local development

### Easiest Windows path

With Docker Desktop installed, double-click `start_local.bat`. The service binds only to `127.0.0.1`, stores its campaign in a named Docker volume, and uses `loreforge` as the local-only editor password unless you set `ADMIN_PASSWORD`.

### Docker

```bash
docker build -t loreforge .
docker run --rm -p 8000:8000 \
  -e ADMIN_PASSWORD=dev-password \
  -v loreforge-data:/data \
  loreforge
```

Open:

- Player wiki: <http://localhost:8000/>
- GM editor: <http://localhost:8000/admin>

### Python development without Docker

You need a local LaTeX distribution containing `latexmk` plus your chosen engine.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# Point data somewhere writable for development.
# PowerShell: $env:DATA_DIR="$PWD/.data"
# bash/zsh:
export DATA_DIR="$PWD/.data"
export ADMIN_PASSWORD="dev-password"

uvicorn app.main:app --reload
```

## How the LaTeX → wiki conversion works

Loreforge deliberately does **not** replace TeX as the authoritative PDF renderer. The PDF preview is generated by your actual LaTeX engine. The player wiki is a semantic companion view.

The converter:

- chooses the main file using stored settings and common names (`main.tex`, `book.tex`, `campaign.tex`, `setting.tex`, `world.tex`), then scores remaining candidates by `\documentclass`, `\begin{document}`, `\input`, and `\include` usage;
- recursively resolves included `.tex` files while preventing path traversal;
- uses `\part`, `\chapter`, `\section`, `\subsection`, and `\subsubsection` to build the codex;
- understands common inline formatting, lists, quotations, links and images;
- converts `longtable`, `tabular`, `tabular*`, `tabularx`, and `tabulary` into responsive HTML tables while consuming TeX column specifications such as `>{\raggedright}p{3.5cm}` so they never leak into prose;
- treats `\pon{Name}` as a Person-of-Note article root: following Profile/Biography sections stay in one article, label/value `multicols` profiles become structured metadata grids, and common TikZ-overlay NPC artwork becomes responsive portrait art;
- interprets common image intent (`figure`, `wrapfigure`, TikZ overlay art, `width`, `scale`, portrait/panorama aspect ratio) and keeps full-resolution click-to-zoom;
- detects custom `\newcommand` definitions and preserves their argument content;
- renders macros with names resembling `npc`, `character`, `location`, `place`, `lorebox`, `note`, etc. as richer wiki callouts;
- records unresolved images and discovered packages/macros in **Project → Formatting analysis**.

This is intentionally tolerant. A campaign with a giant custom `.cls` file should still produce useful lore even when the HTML renderer does not know every visual TeX primitive.

### Pathfinder 2e rule/stat-block macros

Loreforge has native web renderers for the campaign commands you supplied. Your definitions remain unchanged and continue to control the PDF; Loreforge only recognizes their *usage* when building the player Codex:

```latex
\feat{Name}{Level}{Traits}{Description}
\action{Name}{\actionOne}{Traits}{Description}
\itemtemplate{Name}{Item 5}{Traits}{Description}

\begin{monster}{Creature Name}{Level}{Traits}{Source}
  \monsterline{Perception}{+12; darkvision}
  \monsterabilityscores{+4}{+3}{+2}{+0}{+2}{-1}
  \monsterdefenses{21}{Fort +13, Ref +12, Will +10}{HP 75}{Resistance 5 fire}
  \monsterspeed{30 feet}
  \monstersection{Offense}
  \monsterattack{Melee \actionOne jaws}{15}{reach 10 feet}{2d8+7 piercing}
  \monsterability{Special Ability}{Rules text.}
\end{monster}
```

The player site renders these as responsive Pathfinder-style rule cards and creature stat blocks instead of flattening the four/six-argument macros into prose. `\actionOne`, `\actionTwo`, `\actionThree`, `\reaction`, and `\freeAction` use the images in `Images/Symbols/` when those files exist. `\image{0.5\textwidth}{Images/foo.png}` is also recognized as an image helper.

The GM editor now includes an **PF2e** button beside **Artwork** and **Scene**. It inserts ready-to-fill feat, action, item, monster, stat-line, and action-symbol snippets using these existing commands.

Custom commands that Loreforge does not know explicitly are now parsed with balanced braces for up to eight arguments, so nested `\textbf{...}`, `\emph{...}`, links, and other formatting inside long arguments are not discarded.

### Optional explicit wiki links

Loreforge recognizes:

```latex
\wiki{Temple of the Eternal Flame}{the old temple}
```

The PDF fallback macro can be defined in your source however you like, for example:

```latex
\newcommand{\wiki}[2]{#2}
```

In the player wiki, this becomes a link to the matching slug.

## Invitation-only player access

Open **Admin → Access**. Loreforge defaults to **Invitation links only**. Create one link per player with a recognizable label such as `Sarah` or `Piotr`. Opening that private URL establishes a signed Loreforge session in that browser and sends the player directly into the campaign—there is no shared player password.

Each invitation shows its state, expiry, last-used time, invitation-open count, and remembered browser/device count. When creating a link you can optionally cap it to 1–5 devices in the UI (the backend accepts up to 20). From the same screen you can:

- **Copy link** again at any time;
- **Revoke** it, immediately invalidating browsers authenticated through that invitation on their next protected request;
- **Replace / rotate** it, invalidating the old URL and all sessions from the previous version and clearing remembered devices;
- **Reset devices** without changing the URL, useful after a player changes phone/browser; existing sessions stop working until the player reopens the link;
- open/test an invitation while logged in as GM without consuming one of its player device slots;
- **Restore** a revoked, non-expired invitation;
- set an expiry when creating a link; and
- permanently delete old invitation records.

Invitation tokens are signed with Loreforge's persistent session secret and versioned per player. There is no global player secret to share, and the GM password is never placed in an invitation URL. As with any bearer link, a player can still forward their personal URL to someone else; a low device limit reduces casual sharing but is not identity verification. Treat the URL like a password and revoke/rotate it if it leaks.

Two fallback modes exist for unusual deployments: **Shared Password** uses the legacy `PLAYER_PASSWORD` environment variable, and **Public** removes the player gate entirely. Creating a new personal invitation automatically switches the site back to invitation-only mode.

## GM read → edit source bridge

Open the player site from the same browser where you are logged into `/admin`. Codex entries then show an unobtrusive GM-only **Edit source** button plus a floating edit control that remains available while you scroll. Clicking it opens Campaign Studio at the corresponding `.tex` file and line. On long entity pages such as `\pon{...}` entries, Loreforge retains the source line for nested Profile/Biography/etc. headings, so the floating control follows the section currently in view.

The editor URL uses `?file=...&line=...&from=...`; CodeMirror jumps to the requested line and the top bar shows **Back to entry**. This makes quick spelling/lore corrections a read → edit → return workflow rather than a manual file-tree search.

## Codex Studio and art direction

Open **Admin → Codex Studio** and select either a chapter or a specific entry.

For a **chapter**, assign a table-of-contents cover. For an **entry**, you can independently assign:

- table-of-contents thumbnail;
- hero/banner artwork;
- full-page background artwork;
- cinematic banner, split, portrait-panel, or minimal hero style;
- standard, wide, or cinematic article width;
- background opacity and X/Y focal point;
- featured-home-page status;
- public, teaser, or hidden discovery state.

For large chapter/section blocks, Loreforge can automatically use the first usable image rendered inside one of that chapter's entries. The Codex Studio chapter inspector labels this `AUTO · SECTION BACKGROUND`, so you can tell the automatic section treatment from manually curated artwork. A manually chosen chapter image always wins. Entry-level artwork remains deliberate and is not automatically painted behind individual navigation headlines.

The editor toolbar has two complementary tools:

### Artwork

**Artwork** inserts a standard LaTeX `figure` plus a web-only comment. The PDF therefore remains portable to Overleaf, while the wiki can use richer responsive placement:

```latex
% loreforge-image: layout=edge-right width=34 opacity=0.80 blend=soft-light frame=none
\begin{figure}[htbp]
  \centering
  \includegraphics[width=.34\linewidth]{Images/sigil.png}
\end{figure}
```

You can also use `watermark`, `fullbleed`, `breakout`, `banner`, `portrait`, `left`, `right`, `edge-left`, and the ordinary automatic layout. If you never use these comments, all pre-v1.2 automatic figure/portrait behavior remains active.

### Scene

Select a paragraph, quotation, subsection introduction, or other ordinary LaTeX and press **Scene**. Loreforge wraps it like this:

```latex
% loreforge-panel-start: image="Images/Places/stormgate.jpg" opacity=0.38 x=65 y=42 tone=arcane min_height=360 parallax=true
The gate wakes only when both moons stand above the eastern sea.
% loreforge-panel-end
```

TeX sees two comments plus the unchanged prose. The player wiki renders the same passage as an atmospheric image-backed scene. This is useful for chapter openings, dream sequences, major reveals, cities, dungeons, gods, and historical interludes.

## Lore relationships

Loreforge can automatically link the first natural mention of a **unique** codex entry name in another article. It deliberately ignores ambiguous duplicate titles and generic headings. Disable this globally with **Admin → Project → Automatically cross-link codex names in prose** if you prefer only explicit links.

Automatic and explicit links feed three systems:

1. **Related lore** suggestions on entries;
2. **Backlinks** showing which other entries refer to the current subject; and
3. **Lore Network** in the player navigation, an interactive visual graph of the setting.

This means the wiki becomes progressively more interconnected as the LaTeX source grows, without requiring a second manual relationship database.

## Build Doctor diagnostics

Every failed build shows a prominent **First blocking error** excerpt. This fallback is intentionally independent of the clickable file/line parser, so unfamiliar TeX/package failures cannot leave the editor at a generic “Compilation failed” state. **Copy diagnostic bundle** copies that excerpt, up to 20 structured errors, and the recent engine-log tail for troubleshooting.

### Automatic section-block backgrounds

The large Codex chapter/section cards are image-backed by default without bringing back the old tiny thumbnail icons. Loreforge searches the entries inside each section for the first meaningful rendered image (skipping PF2e action symbols and other utility icons) and uses it as a darkened background across the **whole section block**. Individual entry headlines and the desktop article sidebar remain text-only. A manually chosen chapter **Table-of-contents artwork** image overrides the automatic section image. Disable **Project → Use the first image as section-block background by default** to return the large blocks to the plain treatment.

## Compile result verification

Loreforge verifies the final PDF rather than trusting only `latexmk`'s process exit code. Some large XeLaTeX projects can finish `xdvipdfmx`, write a valid PDF, and still leave a non-zero wrapper status from an earlier rule. If the PDF is valid, no real TeX source error is present, and the build log explicitly confirms the final target (for example `All targets (main.pdf) are up-to-date`), Loreforge treats the build as successful instead of showing a false `Compilation failed`.

## Compile status and large XeLaTeX projects

Loreforge evaluates the **terminal** build state, not merely latexmk's process return code. This matters for large XeLaTeX books where an earlier pass may fail or be retried, while a later `xdvipdfmx` stage successfully writes the final PDF. If the final successful PDF witness occurs after all fatal markers, Loreforge accepts the build and does not mislabel old diagnostics from an earlier pass as the current blocker.

For large campaign books, Loreforge also avoids duplicating the finished PDF on the persistent volume. The canonical output remains beside the main `.tex` file and `/preview/pdf` serves it directly; `build/campaign.pdf` is only a zero-copy link when the host supports links. Upgrading from older versions automatically removes an obsolete full-copy preview when the canonical PDF still exists. This is important on small Railway volumes, where a 140 MB campaign PDF should consume roughly 140 MB, not roughly 280 MB merely to support the preview pane.

## Live editing behavior

- Browser changes autosave after roughly 0.7 seconds of inactivity.
- The player-wiki representation is rebuilt on save.
- The real LaTeX PDF compiles after a slightly longer idle delay, or immediately with **Compile** / `Ctrl+Enter`.
- `Ctrl+S` saves immediately.
- LaTeX build errors are shown in the Build Log tab; file/line diagnostics are clickable when the engine emits `file.tex:line:` diagnostics.

## Maps

Open **Admin → Maps**:

1. Create a map and upload PNG, JPG or WebP.
2. Press **＋ Location**, then click where the marker belongs. Double-click remains available as a shortcut.
3. Drag existing markers directly on the map to reposition them.
4. Choose a marker type, description, player visibility and optional codex page.
5. Open **✦ Atmosphere** to configure the map.
6. Choose a preset or independently toggle any of the fantasy layers. Intensity, animation speed, marker size/labels/pulses, viewport fit mode and edge locking are also configurable.
7. Press **Save map** to publish those settings to the player atlas.

### Map movement

The default player setting is **Edge-locked / cover**. Loreforge calculates the minimum zoom needed to cover the viewport and clamps X/Y movement so the user can never pan beyond the physical map boundaries. This fixes the "floating map" behavior where a player could previously shove the image into one corner and expose empty background.

You can deliberately switch a map to **Show whole map / contain** from its Atmosphere panel. The map remains clamped, but letterboxing is allowed when the image and viewport aspect ratios differ.

### Fantasy atmosphere layers

All effects are browser-rendered overlays; the uploaded map file itself is never modified. Available switches include:

- Atmosphere: moving clouds, cloud shadows, rolling fog, aurora, starfield.
- Weather/terrain: rain, lightning, snow, ashfall, sand/dust, ocean shimmer.
- Magic/life: embers, fireflies, arcane motes, ley lines, drifting leaves, distant birds.
- Cartography: vignette, parchment warmth, moonlit tint, cartographer grid, compass rose.

Global **Intensity** and **Motion** sliders let you tune the whole combination without micromanaging every individual effect. Players with reduced-motion preferences automatically receive greatly reduced animation speed.

The player atlas also includes a type-filterable location panel, fixed-size markers that remain readable while zooming, marker focus behavior that keeps the selected location visible beside its lore drawer, and touch pinch zoom.

## Security notes

- The GM editor is password protected with `ADMIN_PASSWORD`.
- The player site is **invitation-only by default**. Revoked/rotated invitation sessions are revalidated on protected requests, including Codex, Atlas, Lore Network, images/uploads, search, and PDF preview.
- Railway deployments use Secure session cookies by default; local HTTP development automatically remains usable.
- Zip imports are extracted with path-traversal protection.
- File APIs cannot escape the campaign project root.
- LaTeX compilation disables shell escape by default and asks TeX to restrict file access. If your trusted campaign requires `minted` or another shell-escape feature, you can explicitly set `LATEX_ALLOW_SHELL_ESCAPE=1`.
- Do **not** enable shell escape on a deployment where untrusted people can edit LaTeX.

## Compatibility limits

The Docker image intentionally does not install `texlive-full`, because that image would be enormous. It includes the most common LaTeX, graphics, font, XeTeX and LuaTeX packages. If your current Overleaf source uses an uncommon system package, either:

- add the relevant Debian/TeX Live package to the `Dockerfile`; or
- include the custom `.sty` / `.cls` file in the project, as you normally can in Overleaf.

The wiki renderer is semantic rather than pixel-identical to the PDF. Your PDF preview is the exact place to verify TeX formatting; the player wiki intentionally reformats the same content into a responsive website.

## Tests

```bash
pip install pytest
pytest -q
```

## Why the campaign is not committed back to GitHub on every keystroke

Doing that would create a flood of commits and, with Railway GitHub auto-deploys enabled, could repeatedly redeploy the whole application while you type. Loreforge therefore treats the persistent project volume as the authoring store and provides project ZIP export for backups/Overleaf interchange. GitHub remains the clean application/deployment repository.

## Fontspec / custom font projects

`fontspec` cannot compile under pdfLaTeX. Loreforge now detects `fontspec`, `\setmainfont`, `\setsansfont`, `\setmonofont`, `unicode-math`, and `polyglossia` and automatically chooses XeLaTeX. Lua-only source is switched to LuaLaTeX. This works even if an older Railway deployment still has `LATEX_ENGINE=pdflatex`; `LATEX_ENGINE=auto` is nevertheless the recommended setting.

The Docker image includes OpenType **TeX Gyre** fonts and **EB Garamond**, so the commonly used:

```latex
\setmainfont{TeX Gyre Adventor}
```

works after rebuilding the Railway image. For a different private font, keep the `.otf`/`.ttf` in the LaTeX project and reference it through normal `fontspec` file/path options, or add the relevant Debian font package to the Dockerfile.

## Troubleshooting: `latexmk` says “Nothing to do” but also “pdflatex: gave an error”

That exact combination is usually a stale failed-build state in `latexmk`: its dependency database remembers a previous engine failure, then a later run decides there is nothing new to compile and only repeats the old failure summary.

Loreforge detects this pattern automatically. It removes only generated LaTeX dependency/auxiliary state (`.fdb_latexmk`, `.fls`, `.aux`, `.toc`, etc.), retries with a forced dependency rebuild, and—if the wrapper still has no useful source diagnostic—runs the selected TeX engine directly once to recover the actual error message. The **Build log** shows a **Build Doctor** card describing any recovery step and likely fixes.

You can still press **↻ Clean** manually at any time. It does not delete your `.tex`, images, `.sty`, `.cls`, bibliography, maps, or Loreforge metadata; it only clears generated compilation state before rebuilding.

If the underlying problem is real rather than stale state—for example a missing package, missing project `.sty`, undefined command, unmatched brace/environment, shell-escape requirement, or unavailable font—Build Doctor will keep the compile failed and show that cause instead of disguising it as the generic `latexmk` summary.

## Troubleshooting: `No space left on device` while importing

Loreforge v1.0.1+ stages uploaded ZIP archives, extraction, and transactional rollback data in the service's ephemeral temporary filesystem rather than the persistent `/data` volume. This avoids requiring several copies of the same Overleaf project on the Railway volume during import.

If you previously attempted an import with an older Loreforge build, open **Admin → Project → Railway persistence** and click **Clean failed-import leftovers**. The cleanup only targets legacy `project-backup-*`, `import-*`, and `upload-*.zip` artifacts; it does not delete the active `/data/project` campaign.

The Project screen also reports total, used, and free persistent storage. If the final uncompressed campaign itself does not fit, increase the Railway volume mounted at `/data` (paid Railway plans support live volume resizing) or reduce unused assets in the Overleaf source ZIP.


## v1.1 formatting and atlas fixes

This build adds regression coverage for longtable column-spec leakage, `\pon` entity grouping/profile rendering, TikZ NPC portrait extraction, persistent-volume migration for map atmosphere settings, and effect-setting validation. The test suite now includes regression coverage for Build Doctor recovery, automatic XeLaTeX selection for fontspec projects, PF2e semantic feat/action/item/monster rendering, scene art, deliberate TOC art, lore linking, batch Build Doctor repairs, and duplicate-geometry consolidation.

### Build Doctor engine sanity check (v1.3.5)

If the workspace says `Compilation failed · xelatex`, Build Doctor no longer infers a pdfLaTeX/fontspec problem merely because the words `fontspec` and `fatal` occur somewhere in the same long log. It reports that incompatibility only when TeX explicitly says fontspec was run under pdfTeX. Loreforge also compares the selected engine with the engine banner actually seen in the log; a mismatch usually points to a project-local `latexmkrc`/`.latexmkrc` override.

### Large XeLaTeX books and `.xdv` output (v1.3.6)

When `latexmk -xelatex` runs, XeLaTeX deliberately typesets to an intermediate `.xdv` file and `latexmk` then calls `xdvipdfmx` to create the final PDF. Seeing a line such as `Output written on main.xdv (347 pages, ...)` therefore means the **TeX typesetting stage completed**; it is not itself an error.

Loreforge now handles that pipeline explicitly. Large projects receive an adaptive build allowance, AUTO-selected XeLaTeX no longer clears auxiliary files on every compile, and a fresh `.xdv` can be converted to PDF in a separate recovery stage if the outer `latexmk` process stops before conversion. If `xdvipdfmx` fails, its own diagnostic is promoted to **FIRST BLOCKING ERROR**.

`LATEX_TIMEOUT` is now treated as the minimum per-stage allowance. Large XeLaTeX/LuaLaTeX projects may automatically receive 180–300 seconds so a long illustrated campaign book is not killed by the historical 60-second default.
