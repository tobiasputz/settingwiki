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
- **Fails gracefully on unusual LaTeX.** Unknown commands are unwrapped so their human-readable arguments are not silently discarded. Custom macros whose names look like NPC/location/lore-box commands are rendered as callouts in the wiki.
- **Compiles the original PDF.** The Docker image includes `latexmk`, pdfLaTeX, XeLaTeX, LuaLaTeX, common LaTeX-extra packages, fonts and graphics packages. Project-local `.cls` and `.sty` files work normally.
- **Interactive atlas.** Upload a map image, double-click to place markers, drag them into position, attach descriptions and link markers to codex pages. Markers can be player-visible or GM-only.
- **Animated maps.** Player maps support wheel/button zoom, drag-to-pan, animated drifting clouds, map reset, marker drawers and codex links.
- **Revision safety.** Loreforge keeps up to 40 saved revisions of each file edited in the browser.
- **Separate player and GM access.** The player wiki can be public or protected with `PLAYER_PASSWORD`; the editor uses `ADMIN_PASSWORD`.

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
PLAYER_PASSWORD=<password for the player-facing wiki>
LATEX_ENGINE=pdflatex       # or xelatex / lualatex
LATEX_TIMEOUT=60
LATEX_ALLOW_SHELL_ESCAPE=0
```

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
- detects custom `\newcommand` definitions and preserves their argument content;
- renders macros with names resembling `npc`, `character`, `location`, `place`, `lorebox`, `note`, etc. as richer wiki callouts;
- records unresolved images and discovered packages/macros in **Project → Formatting analysis**.

This is intentionally tolerant. A campaign with a giant custom `.cls` file should still produce useful lore even when the HTML renderer does not know every visual TeX primitive.

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

## Live editing behavior

- Browser changes autosave after roughly 0.7 seconds of inactivity.
- The player-wiki representation is rebuilt on save.
- The real LaTeX PDF compiles after a slightly longer idle delay, or immediately with **Compile** / `Ctrl+Enter`.
- `Ctrl+S` saves immediately.
- LaTeX build errors are shown in the Build Log tab; file/line diagnostics are clickable when the engine emits `file.tex:line:` diagnostics.

## Maps

Open **Admin → Maps**:

1. Create a map and upload PNG, JPG or WebP.
2. Double-click the map to create a marker.
3. Drag the marker to reposition it.
4. Set the marker type, description, visibility and optional codex page.
5. Enable animated clouds and tune opacity/speed.

The player map supports smooth pan/zoom and hides all GM-only markers.

## Security notes

- The editor is password protected.
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
