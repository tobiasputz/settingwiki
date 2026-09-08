from __future__ import annotations

import html
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from html.parser import HTMLParser

from .config import Settings
from .storage import get_setting, list_codex_presentations, safe_project_path, set_setting


COMMENT_RE = re.compile(r"(?<!\\)%.*$")
INCLUDE_RE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")
HEADING_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection)\*?\s*\{([^{}]+)\}")
TITLE_RE = re.compile(r"\\title\s*\{([^{}]+)\}")
AUTHOR_RE = re.compile(r"\\author\s*\{([^{}]+)\}")
NEWCOMMAND_RE = re.compile(r"\\(?:newcommand|renewcommand)\s*\{?\\([A-Za-z@]+)\}?\s*(?:\[(\d+)\])?")
ENV_RE = re.compile(r"\\(?:newenvironment|NewDocumentEnvironment)\s*\{([^{}]+)\}")
DEFINECOLOR_RE = re.compile(r"\\definecolor\s*\{([^{}]+)\}\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
IMAGE_RE = re.compile(r"\\includegraphics(?:\[([^\]]*)\])?\s*\{([^{}]+)\}")
ENTITY_ROOT_MACROS = {"pon"}
TABLE_ENVIRONMENTS = ("longtable", "tabular", "tabular*", "tabularx", "tabulary")


@dataclass
class SourceLine:
    path: str
    line: int
    text: str


@dataclass
class WikiPage:
    slug: str
    title: str
    chapter: str | None
    level: str
    html: str
    plain_text: str
    source_file: str
    source_line: int
    excerpt: str
    order: int


@dataclass
class BuildResult:
    ok: bool
    main_file: str
    pdf_path: str | None
    duration: float
    command: list[str]
    log: str
    errors: list[dict]
    recovery: str = ""
    suggestions: list[str] = field(default_factory=list)
    effective_engine: str = ""
    partial_pdf: bool = False
    failure_excerpt: str = ""


def strip_comments(line: str) -> str:
    return COMMENT_RE.sub("", line)


def choose_main(settings: Settings) -> str:
    configured = get_setting(settings, "main_file", "")
    if configured:
        path = safe_project_path(settings, configured)
        if path.exists():
            return configured
    files = list(settings.project_dir.rglob("*.tex"))
    if not files:
        raise ValueError("No .tex files exist in the project.")
    preferred = ["main.tex", "book.tex", "campaign.tex", "setting.tex", "world.tex"]
    for name in preferred:
        for p in files:
            if p.name.lower() == name:
                rel = p.relative_to(settings.project_dir).as_posix()
                set_setting(settings, "main_file", rel)
                return rel
    scored = []
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        score = 20 * int("\\documentclass" in text) + 3 * text.count("\\begin{document}") + text.count("\\input") + text.count("\\include")
        scored.append((score, p))
    chosen = max(scored, key=lambda x: x[0])[1]
    rel = chosen.relative_to(settings.project_dir).as_posix()
    set_setting(settings, "main_file", rel)
    return rel


def resolve_include(base: Path, raw: str, project_root: Path) -> Path | None:
    raw = raw.strip()
    candidate = base.parent / raw
    if not candidate.suffix:
        candidate = candidate.with_suffix(".tex")
    try:
        resolved = candidate.resolve()
        root = project_root.resolve()
        if resolved != root and root not in resolved.parents:
            return None
        return resolved if resolved.exists() else None
    except OSError:
        return None


def expand_project(settings: Settings, main_file: str | None = None) -> list[SourceLine]:
    main_rel = main_file or choose_main(settings)
    main = safe_project_path(settings, main_rel)
    visited: set[Path] = set()
    out: list[SourceLine] = []

    def walk(path: Path) -> None:
        path = path.resolve()
        if path in visited or not path.exists():
            return
        visited.add(path)
        rel = path.relative_to(settings.project_dir.resolve()).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            clean = strip_comments(line)
            cursor = 0
            found = False
            for match in INCLUDE_RE.finditer(clean):
                found = True
                before = clean[cursor:match.start()]
                if before.strip():
                    out.append(SourceLine(rel, line_no, before))
                inc = resolve_include(path, match.group(1), settings.project_dir)
                if inc:
                    walk(inc)
                else:
                    out.append(SourceLine(rel, line_no, f"% [Loreforge: unresolved include {match.group(1)}]"))
                cursor = match.end()
            if found:
                after = clean[cursor:]
                if after.strip():
                    out.append(SourceLine(rel, line_no, after))
            else:
                out.append(SourceLine(rel, line_no, line))

    walk(main)
    # Preserve orphan tex files in diagnostics, but do not inject them into the public book automatically.
    return out


def analyze_project(settings: Settings) -> dict:
    main = choose_main(settings)
    files = list(settings.project_dir.rglob("*.tex"))
    # Custom campaign-book commands are very often defined in a local .sty or
    # .cls rather than in main.tex.  Include those definitions in semantic
    # analysis while still reporting tex_files separately.
    definition_files = files + list(settings.project_dir.rglob("*.sty")) + list(settings.project_dir.rglob("*.cls"))
    joined = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in definition_files)
    main_text = safe_project_path(settings, main).read_text(encoding="utf-8", errors="replace")
    title = (TITLE_RE.search(main_text).group(1).strip() if TITLE_RE.search(main_text) else get_setting(settings, "site_title", "")) or "Campaign Atlas"
    author = AUTHOR_RE.search(main_text).group(1).strip() if AUTHOR_RE.search(main_text) else ""
    macros = []
    seen = set()
    for match in NEWCOMMAND_RE.finditer(joined):
        name = match.group(1)
        if name not in seen:
            macros.append({"name": name, "args": int(match.group(2) or 0), "kind": _infer_macro_kind(name)})
            seen.add(name)
    envs = sorted(set(ENV_RE.findall(joined)))
    colors = [{"name": a, "model": b, "value": c} for a, b, c in DEFINECOLOR_RE.findall(joined)]
    headings = [{"level": m.group(1), "title": clean_inline_text(m.group(2))} for m in HEADING_RE.finditer("\n".join(x.text for x in expand_project(settings, main)))]
    image_refs = [m.group(2) for m in IMAGE_RE.finditer(joined)]
    missing_images = []
    for ref in image_refs:
        found = _find_asset(settings.project_dir, ref)
        if not found:
            missing_images.append(ref)
    packages = re.findall(r"\\usepackage(?:\[[^\]]*\])?\{([^{}]+)\}", joined)
    return {
        "main_file": main,
        "title": clean_inline_text(title),
        "author": clean_inline_text(author),
        "tex_files": len(files),
        "headings": headings,
        "custom_macros": macros[:150],
        "custom_environments": envs[:150],
        "colors": colors[:80],
        "packages": sorted(set(x.strip() for group in packages for x in group.split(",") if x.strip())),
        "image_references": image_refs,
        "missing_images": missing_images,
        "recommended_engine": _effective_latex_engine(settings)[0],
    }


def _infer_macro_kind(name: str) -> str:
    n = name.lower()
    # `pon` is commonly used in campaign books as "Person of Note".  It is
    # structurally different from an inline NPC callout: it starts an entity
    # article and the following \section/\subsection commands belong to that
    # article.  Keep this explicit because short custom macro names cannot be
    # inferred reliably from their spelling alone.
    if n in ENTITY_ROOT_MACROS:
        return "entity-heading"
    if n in {"feat", "action", "itemtemplate"}:
        return "pf2e-rule"
    if n in {"actionone", "actiontwo", "actionthree", "reaction", "freeaction"}:
        return "pf2e-symbol"
    if n.startswith("monster"):
        return "pf2e-stat"
    if n == "image":
        return "image"
    if any(k in n for k in ("chapter", "section", "title", "heading")):
        return "heading"
    if any(k in n for k in ("npc", "character", "person")):
        return "npc-card"
    if any(k in n for k in ("place", "location", "settlement", "region")):
        return "location-card"
    if any(k in n for k in ("box", "note", "aside", "lore", "warning", "tip")):
        return "callout"
    return "inline"


def clean_inline_text(text: str) -> str:
    for _ in range(8):
        text = re.sub(r"\\(?:textbf|textit|emph|underline|texttt|textrm|textsf|mbox)\s*\{([^{}]*)\}", r"\1", text)
        text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", "", text)
    replacements = {r"\&": "&", r"\%": "%", r"\_": "_", r"\#": "#", "~": " "}
    for a, b in replacements.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text.replace("{", "").replace("}", "")).strip()


def slugify(value: str) -> str:
    value = clean_inline_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "page"


def _read_braced(text: str, pos: int) -> tuple[str, int] | None:
    """Read one balanced `{...}` argument starting at/after *pos*.

    Regex-only parsing breaks immediately for useful campaign macros because feat,
    item and monster descriptions routinely contain nested formatting commands.
    This small balanced reader is intentionally conservative but understands the
    nesting that normal LaTeX command arguments use.
    """
    n = len(text)
    while pos < n and text[pos].isspace():
        pos += 1
    if pos >= n or text[pos] != "{":
        return None
    depth = 0
    start = pos + 1
    i = pos
    while i < n:
        ch = text[i]
        escaped = i > 0 and text[i - 1] == "\\"
        if not escaped:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i], i + 1
        i += 1
    return None


def _replace_balanced_command(raw: str, name: str, nargs: int, replacer) -> str:
    """Replace `\\name{...}` calls while preserving nested braces in arguments."""
    pattern = re.compile(r"\\" + re.escape(name) + r"\b")
    out: list[str] = []
    cursor = 0
    while True:
        match = pattern.search(raw, cursor)
        if not match:
            out.append(raw[cursor:])
            break
        out.append(raw[cursor:match.start()])
        pos = match.end()
        args: list[str] = []
        valid = True
        for _ in range(nargs):
            parsed = _read_braced(raw, pos)
            if not parsed:
                valid = False
                break
            value, pos = parsed
            args.append(value)
        if not valid:
            out.append(raw[match.start():match.end()])
            cursor = match.end()
            continue
        out.append(replacer(args))
        cursor = pos
    return "".join(out)


def _replace_balanced_environment(raw: str, name: str, nargs: int, replacer) -> str:
    """Replace a non-nested custom environment with balanced begin arguments."""
    begin_re = re.compile(r"\\begin\{" + re.escape(name) + r"\}")
    end_marker = r"\end{" + name + "}"
    out: list[str] = []
    cursor = 0
    while True:
        match = begin_re.search(raw, cursor)
        if not match:
            out.append(raw[cursor:])
            break
        out.append(raw[cursor:match.start()])
        pos = match.end()
        args: list[str] = []
        valid = True
        for _ in range(nargs):
            parsed = _read_braced(raw, pos)
            if not parsed:
                valid = False
                break
            value, pos = parsed
            args.append(value)
        if not valid:
            out.append(raw[match.start():match.end()])
            cursor = match.end()
            continue
        end = raw.find(end_marker, pos)
        if end < 0:
            out.append(raw[match.start():])
            break
        body = raw[pos:end]
        out.append(replacer(args, body))
        cursor = end + len(end_marker)
    return "".join(out)


def _project_engine_signals(settings: Settings) -> dict:
    """Detect source features that require XeLaTeX/LuaLaTeX.

    This deliberately scans .tex/.sty/.cls files because Overleaf projects often
    put fontspec in a local style/class rather than main.tex.
    """
    chunks: list[str] = []
    for suffix in ("*.tex", "*.sty", "*.cls"):
        for path in settings.project_dir.rglob(suffix):
            try:
                chunks.append("\n".join(strip_comments(x) for x in path.read_text(encoding="utf-8", errors="replace").splitlines()))
            except OSError:
                pass
    source = "\n".join(chunks)
    fontspec = bool(re.search(r"\\(?:usepackage(?:\[[^\]]*\])?\{[^}]*fontspec[^}]*\}|setmainfont\b|setsansfont\b|setmonofont\b|newfontfamily\b|fontspec\b|usepackage(?:\[[^\]]*\])?\{[^}]*unicode-math[^}]*\}|usepackage(?:\[[^\]]*\])?\{[^}]*polyglossia[^}]*\})", source, re.IGNORECASE))
    lua = bool(re.search(r"\\(?:directlua|begin\{luacode\}|usepackage(?:\[[^\]]*\])?\{[^}]*luacode[^}]*\})", source, re.IGNORECASE))
    return {"fontspec": fontspec, "lua": lua}


def _effective_latex_engine(settings: Settings) -> tuple[str, str]:
    """Return the safe engine and an optional Build Doctor explanation.

    ``auto`` resolving to XeLaTeX is not an engine *change* on every build.  It is
    simply the project's effective engine.  The previous wording caused the
    compiler to purge auxiliary state on every compile for fontspec projects,
    which made large books unnecessarily slow and prevented latexmk from
    converging incrementally.
    """
    requested = (settings.latex_engine or "auto").strip().lower()
    if requested not in {"auto", "pdflatex", "xelatex", "lualatex"}:
        requested = "auto"
    signals = _project_engine_signals(settings)
    required = "lualatex" if signals["lua"] else ("xelatex" if signals["fontspec"] else "")
    if required:
        # LuaLaTeX also supports fontspec; a user who deliberately selected it
        # should not be downgraded to XeLaTeX.
        if signals["fontspec"] and requested == "lualatex" and not signals["lua"]:
            return "lualatex", ""
        reason = "LuaLaTeX-only commands" if required == "lualatex" else "fontspec / \\setmainfont"
        if requested == "auto":
            return required, f"Detected {reason} in the project and auto-selected {required}."
        if requested != required:
            return required, f"Detected {reason} in the project and safely switched from configured {requested} to {required}."
        return required, ""
    if requested == "auto":
        return "pdflatex", ""
    return requested, ""


def presentation_asset_url(settings: Settings, ref: str | None) -> str:
    ref = str(ref or "").strip()
    if not ref:
        return ""
    if ref.startswith("project:"):
        return asset_url(settings, ref.split(":", 1)[1]) or ""
    if ref.startswith("upload:"):
        rel = ref.split(":", 1)[1].replace("\\", "/").lstrip("/")
        return "/uploads/" + quote(rel, safe="/")
    if ref.startswith("/project-asset/") or ref.startswith("/uploads/"):
        return ref
    # Backwards-compatible: treat a bare path as a project asset first.
    return asset_url(settings, ref) or ""


def _presentation_for_web(settings: Settings, raw: dict | None) -> dict:
    raw = dict(raw or {})
    raw["toc_image_url"] = presentation_asset_url(settings, raw.get("toc_image"))
    raw["hero_image_url"] = presentation_asset_url(settings, raw.get("hero_image"))
    raw["background_image_url"] = presentation_asset_url(settings, raw.get("background_image"))
    return raw




_GENERIC_LINK_TITLES = {
    "profile", "biography", "history", "introduction", "overview", "setting",
    "people", "places", "locations", "items", "factions", "religion", "deities",
    "geography", "culture", "politics", "timeline", "appendix", "notes",
}


def _annotate_headings(html_body: str) -> tuple[str, list[dict]]:
    """Give article headings stable anchors and return a compact page outline."""
    used: dict[str, int] = {}
    outline: list[dict] = []

    def sub(m: re.Match) -> str:
        level = int(m.group(1))
        inner = m.group(2)
        title = html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        base = slugify(title) or "section"
        used[base] = used.get(base, 0) + 1
        anchor = base if used[base] == 1 else f"{base}-{used[base]}"
        outline.append({"level": level, "id": anchor, "title": title})
        return f'<h{level} id="{html.escape(anchor, quote=True)}">{inner}<a class="heading-anchor" href="#{html.escape(anchor, quote=True)}" aria-label="Link to {html.escape(title, quote=True)}">#</a></h{level}>'

    rendered = re.sub(r"<h([2-4])>(.*?)</h\1>", sub, html_body, flags=re.DOTALL)
    return rendered, outline


def _first_rendered_image_url(html_body: str) -> str:
    """Return the first *content* image suitable for atmospheric navigation art.

    PF2e action glyphs are real image tags too, but using a one-action/reaction
    symbol as a full navigation background is almost never useful.  Skip the
    project's Symbols folder and action-symbol markup, then use the next image.
    """
    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html_body, flags=re.IGNORECASE):
        src = html.unescape(match.group(1))
        src_lower = src.lower().replace("%20", " ")
        nearby = html_body[max(0, match.start() - 220):match.end()].lower()
        if "/images/symbols/" in src_lower or "pf2-action-symbol" in nearby:
            continue
        return src
    return ""


class _CodexAutoLinker(HTMLParser):
    """Link the first natural mention of other codex entries in prose.

    Existing links, headings, code and image captions are intentionally skipped.
    This keeps the feature useful rather than turning a long article into a wall of links.
    """
    SKIP_TAGS = {"a", "code", "pre", "script", "style", "h1", "h2", "h3", "h4", "button", "figcaption"}

    def __init__(self, targets: dict[str, tuple[str, str]], self_slug: str):
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.targets = {k: v for k, v in targets.items() if v[0] != self_slug}
        self.used: set[str] = set()
        self.skip_depth = 0
        terms = sorted((title for title, (slug, _) in self.targets.items() if slug != self_slug), key=len, reverse=True)
        self.pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(x) for x in terms) + r")(?![\w])", re.IGNORECASE) if terms else None

    def handle_starttag(self, tag, attrs):
        self.out.append(self.get_starttag_text())
        if tag.lower() in self.SKIP_TAGS:
            self.skip_depth += 1

    def handle_startendtag(self, tag, attrs):
        self.out.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        self.out.append(f"</{tag}>")

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")

    def handle_comment(self, data):
        self.out.append(f"<!--{data}-->")

    def handle_data(self, data):
        if self.skip_depth or not self.pattern:
            self.out.append(html.escape(data, quote=False))
            return
        cursor = 0
        chunks: list[str] = []
        for match in self.pattern.finditer(data):
            key = match.group(1).casefold()
            target = self.targets.get(key)
            if not target or key in self.used:
                continue
            chunks.append(html.escape(data[cursor:match.start()], quote=False))
            slug, canonical = target
            chunks.append(f'<a class="wiki-link auto-wiki-link" href="/wiki/{html.escape(slug, quote=True)}" title="Codex: {html.escape(canonical, quote=True)}">{html.escape(match.group(1))}</a>')
            cursor = match.end()
            self.used.add(key)
        chunks.append(html.escape(data[cursor:], quote=False))
        self.out.append("".join(chunks))


def _auto_link_html(html_body: str, targets: dict[str, tuple[str, str]], self_slug: str) -> str:
    linker = _CodexAutoLinker(targets, self_slug)
    try:
        linker.feed(html_body)
        linker.close()
        return "".join(linker.out)
    except Exception:
        return html_body


def build_wiki(settings: Settings) -> dict:
    lines = expand_project(settings)
    analysis = analyze_project(settings)
    dynamic_heading_macros = [
        m for m in analysis.get("custom_macros", [])
        if m.get("kind") in {"heading", "entity-heading"} and int(m.get("args", 0)) >= 1
    ]
    known_dynamic_names = {m["name"] for m in dynamic_heading_macros}
    for name in ENTITY_ROOT_MACROS:
        if name not in known_dynamic_names:
            dynamic_heading_macros.append({"name": name, "args": 1, "kind": "entity-heading"})
    pages: list[WikiPage] = []
    chapter: str | None = None
    current_title: str | None = None
    current_level = "section"
    current_source = analysis["main_file"]
    current_line = 1
    buffer: list[str] = []
    entity_mode = False
    order = 0
    used_slugs: dict[str, int] = {}

    def unique_slug(title: str) -> str:
        base = slugify(title)
        used_slugs[base] = used_slugs.get(base, 0) + 1
        return base if used_slugs[base] == 1 else f"{base}-{used_slugs[base]}"

    def flush() -> None:
        nonlocal buffer, order
        if not current_title:
            buffer = []
            return
        raw = "\n".join(buffer).strip()
        # Chapter/part headings are often structural containers only. Do not
        # create blank player pages when the next meaningful item is a \pon
        # or section; the heading still remains the navigation category.
        if not raw and current_level in {"part", "chapter"}:
            buffer = []
            return
        body_html, plain = latex_fragment_to_html(raw, settings, page_kind=current_level, analysis=analysis)
        excerpt = re.sub(r"\s+", " ", plain).strip()[:240]
        pages.append(WikiPage(
            slug=unique_slug(current_title), title=current_title, chapter=chapter,
            level=current_level, html=body_html, plain_text=plain, source_file=current_source,
            source_line=current_line, excerpt=excerpt, order=order,
        ))
        order += 1
        buffer = []

    in_document = False
    saw_document = False
    for src in lines:
        # Preserve Loreforge's web-only image placement comment until the
        # fragment renderer consumes it. Ordinary LaTeX comments are still
        # stripped here so they never become player-visible prose.
        if re.match(r"^\s*%\s*loreforge-(?:image|panel-start|panel-end)\b", src.text, flags=re.IGNORECASE):
            line = src.text
        else:
            line = strip_comments(src.text)
        if "\\begin{document}" in line:
            saw_document = True
            in_document = True
            line = line.replace("\\begin{document}", "")
        if "\\end{document}" in line:
            line = line.replace("\\end{document}", "")
            should_end = True
        else:
            should_end = False
        if saw_document and not in_document:
            continue
        # Ignore common preamble/meta commands when no document env is used.
        if not in_document and not saw_document and re.match(r"\s*\\(?:documentclass|usepackage|newcommand|renewcommand|newenvironment|definecolor|geometry|hypersetup|title|author|date)\b", line):
            continue
        match = HEADING_RE.search(line)
        dynamic_match = None
        dynamic_info = None
        if not match:
            for info in dynamic_heading_macros:
                dm = re.search(r"\\" + re.escape(info["name"]) + r"\s*\{([^{}]+)\}", line)
                if dm:
                    dynamic_match, dynamic_info = dm, info
                    break
        if match or dynamic_match:
            # A Person-of-Note style macro owns the sections that follow it.
            # In the PDF those sections often live on multiple pages, but on
            # the wiki they make much more sense as one character article.
            if entity_mode and match and match.group(1) in {"section", "subsection", "subsubsection"}:
                buffer.append(line)
                if should_end:
                    in_document = False
                continue
            flush()
            if match:
                level, title = match.group(1), clean_inline_text(match.group(2))
                remainder = HEADING_RE.sub("", line).strip()
                if level in {"part", "chapter"}:
                    entity_mode = False
            else:
                macro_name = dynamic_info["name"].lower()
                if dynamic_info.get("kind") == "entity-heading":
                    level = "entity"
                    entity_mode = True
                else:
                    level = "chapter" if ("chapter" in macro_name or "part" in macro_name) else ("subsection" if "subsection" in macro_name else "section")
                    entity_mode = False
                title = clean_inline_text(dynamic_match.group(1))
                remainder = line[:dynamic_match.start()] + line[dynamic_match.end():]
                remainder = remainder.strip()
            if level in {"part", "chapter"}:
                chapter = title
            current_title = title
            current_level = level
            current_source = src.path
            current_line = src.line
            if remainder:
                buffer.append(remainder)
        elif current_title:
            buffer.append(line)
        if should_end:
            in_document = False
    flush()

    if not pages:
        # Last-resort single page, so unusual documents still render something.
        raw = "\n".join(x.text for x in lines)
        html_body, plain = latex_fragment_to_html(raw, settings, analysis=analysis)
        pages = [WikiPage("setting", analysis["title"], None, "document", html_body, plain, analysis["main_file"], 1, plain[:240], 0)]

    presentations = list_codex_presentations(settings)
    auto_navigation_art = get_setting(settings, "auto_navigation_art", "1").strip().lower() not in {"0", "false", "no", "off"}
    page_dicts: list[dict] = []
    for page in pages:
        item = asdict(page)
        item["presentation"] = _presentation_for_web(settings, presentations.get(("page", page.slug), {}))
        item["html"], item["outline"] = _annotate_headings(item.get("html", ""))
        auto_image = _first_rendered_image_url(item["html"])
        # Navigation artwork can follow the first image in an entry.  Explicit TOC
        # artwork always wins.  The automatic mode is intentionally a project-level
        # preference so campaigns can turn it off without clearing per-entry art.
        # The player UI uses this as a broad, darkened row background -- never as the
        # small thumbnail treatment removed in v1.3.1.
        item["presentation"]["auto_image_url"] = auto_image
        item["presentation"]["suggested_toc_image_url"] = auto_image if not item["presentation"].get("toc_image_url") else ""
        item["presentation"]["display_toc_image_url"] = item["presentation"].get("toc_image_url") or ""
        item["presentation"]["navigation_background_url"] = item["presentation"].get("toc_image_url") or (auto_image if auto_navigation_art else "")
        item["presentation"]["navigation_art_is_auto"] = bool(auto_navigation_art and auto_image and not item["presentation"].get("toc_image_url"))
        page_dicts.append(item)

    # Turn ordinary mentions of unique codex entry names into links. This is
    # intentionally conservative: generic headings and ambiguous duplicate names
    # are ignored, and only the first mention of each target is linked per article.
    title_buckets: dict[str, list[dict]] = {}
    for item in page_dicts:
        title = str(item.get("title") or "").strip()
        key = title.casefold()
        if len(title) >= 4 and key not in _GENERIC_LINK_TITLES:
            title_buckets.setdefault(key, []).append(item)
    auto_targets = {
        key: (items[0]["slug"], items[0]["title"])
        for key, items in title_buckets.items() if len(items) == 1
    }
    auto_link_enabled = get_setting(settings, "auto_link_codex", "1").strip().lower() not in {"0", "false", "no", "off"}
    if auto_link_enabled:
        for item in page_dicts:
            item["html"] = _auto_link_html(item["html"], auto_targets, item["slug"])

    # Explicit and automatically discovered cross-links become useful navigation.
    # Related lore also includes a few nearby entries from the same chapter.
    by_slug = {p["slug"]: p for p in page_dicts}
    backlinks: dict[str, list[str]] = {slug: [] for slug in by_slug}
    for item in page_dicts:
        outgoing = []
        for target in re.findall(r'href=["\']/wiki/([^"\'#?]+)', item.get("html", "")):
            if target in by_slug and target != item["slug"] and target not in outgoing:
                outgoing.append(target)
                backlinks.setdefault(target, []).append(item["slug"])
        item["outgoing_links"] = outgoing
    for item in page_dicts:
        related_slugs = list(item.get("outgoing_links", []))
        for candidate in page_dicts:
            if candidate["slug"] == item["slug"]:
                continue
            if candidate.get("chapter") == item.get("chapter") and candidate["slug"] not in related_slugs:
                related_slugs.append(candidate["slug"])
            if len(related_slugs) >= 4:
                break
        item["related"] = [{"slug": by_slug[x]["slug"], "title": by_slug[x]["title"], "chapter": by_slug[x].get("chapter")} for x in related_slugs[:4] if x in by_slug]
        item["backlinks"] = [{"slug": by_slug[x]["slug"], "title": by_slug[x]["title"], "chapter": by_slug[x].get("chapter")} for x in backlinks.get(item["slug"], [])[:8] if x in by_slug]

    categories: list[dict] = []
    for page in page_dicts:
        label = page.get("chapter") or "Setting"
        category_slug = slugify(label)
        bucket = next((x for x in categories if x["title"] == label), None)
        if not bucket:
            bucket = {
                "title": label, "slug": category_slug, "pages": [],
                "presentation": _presentation_for_web(settings, presentations.get(("category", category_slug), {})),
            }
            categories.append(bucket)
        bucket["pages"].append({
            "slug": page["slug"], "title": page["title"], "excerpt": page["excerpt"],
            "level": page["level"], "presentation": page["presentation"],
        })

    for bucket in categories:
        # Chapter navigation art follows the same preference: explicit chapter art
        # wins, otherwise the first illustrated entry can provide an atmospheric
        # background when automatic navigation artwork is enabled.
        auto_cover = next((
            p.get("presentation", {}).get("auto_image_url")
            for p in bucket.get("pages", [])
            if p.get("presentation", {}).get("auto_image_url")
        ), "")
        bucket["presentation"]["auto_image_url"] = auto_cover
        bucket["presentation"]["suggested_toc_image_url"] = auto_cover if not bucket["presentation"].get("toc_image_url") else ""
        bucket["presentation"]["display_toc_image_url"] = bucket["presentation"].get("toc_image_url") or ""
        bucket["presentation"]["navigation_background_url"] = bucket["presentation"].get("toc_image_url") or (auto_cover if auto_navigation_art else "")
        bucket["presentation"]["navigation_art_is_auto"] = bool(auto_navigation_art and auto_cover and not bucket["presentation"].get("toc_image_url"))

    payload = {
        "title": get_setting(settings, "site_title", "") or analysis["title"],
        "tagline": get_setting(settings, "tagline", "Explore the people, places, histories, and mysteries of the campaign."),
        "author": analysis["author"],
        "generated_at": time.time(),
        "main_file": analysis["main_file"],
        "categories": categories,
        "pages": page_dicts,
        "analysis": analysis,
    }
    settings.build_dir.mkdir(parents=True, exist_ok=True)
    (settings.build_dir / "wiki_index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_wiki(settings: Settings) -> dict:
    path = settings.build_dir / "wiki_index.json"
    if not path.exists():
        return build_wiki(settings)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return build_wiki(settings)


def _find_asset(project_root: Path, ref: str) -> Path | None:
    r"""Resolve an ``\includegraphics`` reference like TeX/Overleaf usually does.

    Campaign projects often rely on ``\graphicspath``, omit file extensions,
    use mixed-case filenames, or move a chapter into a subdirectory.  The wiki
    renderer cannot know TeX's complete graphics search path at this stage, so
    it tries exact paths first and then performs a deterministic project-wide
    suffix/basename lookup.
    """
    ref = ref.strip().strip('"').replace("\\", "/")
    # Common wrapper used for filenames containing spaces.
    detok = re.fullmatch(r"\\detokenize\s*\{(.+)\}", ref, flags=re.DOTALL)
    if detok:
        ref = detok.group(1).strip()
    root = project_root.resolve()
    suffixes = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".svg")
    candidates = [project_root / ref]
    if not Path(ref).suffix:
        candidates.extend(project_root / f"{ref}{ext}" for ext in suffixes)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if (resolved == root or root in resolved.parents) and resolved.exists() and resolved.is_file():
                return resolved
        except OSError:
            pass

    # Overleaf resolves graphics through \graphicspath and the current file's
    # directory.  A suffix match approximates both while still preferring a
    # path that resembles the literal reference.
    normalized = ref.lower().lstrip("./")
    all_files = [x for x in project_root.rglob("*") if x.is_file()]
    suffix_matches: list[Path] = []
    for candidate in all_files:
        rel = candidate.relative_to(project_root).as_posix().lower()
        rel_no_ext = str(Path(rel).with_suffix(""))
        target_no_ext = str(Path(normalized).with_suffix(""))
        if rel == normalized or rel.endswith("/" + normalized):
            return candidate
        if not Path(ref).suffix and (rel_no_ext == target_no_ext or rel_no_ext.endswith("/" + target_no_ext)):
            suffix_matches.append(candidate)
    if suffix_matches:
        return sorted(suffix_matches, key=lambda x: len(x.relative_to(project_root).parts))[0]

    target = Path(ref).name.lower()
    target_stem = Path(target).stem
    basename_matches = [
        x for x in all_files
        if x.name.lower() == target
        or (not Path(ref).suffix and x.stem.lower() == target_stem and x.suffix.lower() in suffixes)
    ]
    if basename_matches:
        return sorted(basename_matches, key=lambda x: (len(x.relative_to(project_root).parts), x.as_posix().lower()))[0]
    return None

def asset_url(settings: Settings, ref: str) -> str | None:
    path = _find_asset(settings.project_dir, ref)
    if not path:
        return None
    rel = path.relative_to(settings.project_dir).as_posix()
    return "/project-asset/" + quote(rel)


def _extract_braced(text: str, pos: int) -> tuple[str | None, int]:
    """Return one balanced {...} argument starting at/after *pos*."""
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text) or text[pos] != "{":
        return None, pos
    depth = 0
    start = pos + 1
    i = pos
    while i < len(text):
        ch = text[i]
        if ch == "{" and (i == 0 or text[i - 1] != "\\"):
            depth += 1
        elif ch == "}" and (i == 0 or text[i - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return None, pos


def _extract_bracketed(text: str, pos: int) -> tuple[str | None, int]:
    """Return one balanced-ish ``[...]`` option starting at/after *pos*."""
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text) or text[pos] != "[":
        return None, pos
    depth = 0
    start = pos + 1
    for i in range(pos, len(text)):
        ch = text[i]
        if ch == "[" and (i == 0 or text[i - 1] != "\\"):
            depth += 1
        elif ch == "]" and (i == 0 or text[i - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
    return None, pos


def _normalize_longtable_sections(content: str) -> str:
    """Keep one longtable header and the real body, not repeated page headers."""
    if "\\endfirsthead" not in content and "\\endhead" not in content:
        return content
    first_head = content.split("\\endfirsthead", 1)[0] if "\\endfirsthead" in content else content.split("\\endhead", 1)[0]
    # Longtable footer declarations appear before the body.  Content after
    # endlastfoot is therefore the actual body in the usual booktabs pattern.
    if "\\endlastfoot" in content:
        body = content.split("\\endlastfoot", 1)[1]
    elif "\\endfoot" in content:
        body = content.split("\\endfoot", 1)[1]
    elif "\\endhead" in content:
        body = content.split("\\endhead", 1)[1]
    else:
        body = ""
    return first_head + "\n" + body


def _render_table_cell_inline(cell: str) -> str:
    text, _ = _strip_table_cell_markup(cell)
    return html.escape(text)


def _strip_table_cell_markup(cell: str) -> tuple[str, int]:
    """Return readable table-cell text and an optional colspan."""
    cell = cell.strip()
    colspan = 1
    m = re.fullmatch(r"\\multicolumn\s*\{(\d+)\}\s*\{[^{}]*\}\s*\{(.*)\}", cell, flags=re.DOTALL)
    if m:
        colspan = max(1, int(m.group(1)))
        cell = m.group(2)
    cell = re.sub(r"\\multirow(?:\[[^\]]*\])?\s*\{[^{}]*\}\s*\{[^{}]*\}\s*\{(.*)\}", r"\1", cell, flags=re.DOTALL)
    cell = re.sub(r"\\(?:cellcolor|rowcolor)\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", "", cell)
    return clean_inline_text(cell), colspan


def _table_to_html(env: str, content: str) -> str:
    """Render useful semantic table content as responsive, readable HTML."""
    if env == "longtable":
        content = _normalize_longtable_sections(content)
    caption = ""
    cap = re.search(r"\\caption(?:\[[^\]]*\])?\s*\{([^{}]*)\}", content)
    if cap:
        caption = clean_inline_text(cap.group(1))
    content = re.sub(r"\\caption(?:\[[^\]]*\])?\s*\{[^{}]*\}", "", content)
    content = re.sub(r"\\label\s*\{[^{}]*\}", "", content)
    content = re.sub(
        r"\\(?:toprule|midrule|bottomrule|hline|cline\s*\{[^{}]*\}|cmidrule(?:\([^)]*\))?\s*\{[^{}]*\}|endfirsthead|endhead|endfoot|endlastfoot|noalign\s*\{[^{}]*\})",
        "\n", content,
    )
    content = re.sub(r"\\addlinespace(?:\[[^\]]*\])?", "\n", content)
    content = re.sub(r"\\(?:small|footnotesize|scriptsize|tiny|normalsize|centering|raggedright|raggedleft)\b", "", content)

    rows_raw = re.split(r"(?<!\\)\\\\(?:\[[^\]]*\])?", content)
    rows: list[list[tuple[str, int]]] = []
    for row in rows_raw:
        row = row.strip()
        if not row:
            continue
        cells_raw = re.split(r"(?<!\\)&", row)
        cells = [_strip_table_cell_markup(c) for c in cells_raw]
        if any(text for text, _ in cells):
            rows.append(cells)
    # Remove an immediately repeated longtable header if a non-standard file
    # placed it outside the usual endfirsthead/endhead markers.
    if len(rows) >= 2 and rows[0] == rows[1]:
        rows.pop(1)
    if not rows:
        return ""

    headers: list[str] = []
    for text, colspan in rows[0]:
        headers.extend([text] * max(1, colspan))
    parts = ['<div class="lore-table-wrap" role="region" aria-label="Table" tabindex="0"><table class="lore-table">']
    if caption:
        parts.append(f"<caption>{html.escape(caption)}</caption>")
    parts.append("<thead><tr>")
    for text, colspan in rows[0]:
        span = f' colspan="{colspan}"' if colspan > 1 else ""
        parts.append(f"<th{span} scope=\"col\">{html.escape(text)}</th>")
    parts.append("</tr></thead>")
    if len(rows) > 1:
        parts.append("<tbody>")
        for row in rows[1:]:
            parts.append("<tr>")
            column_index = 0
            for text, colspan in row:
                span = f' colspan="{colspan}"' if colspan > 1 else ""
                label = headers[column_index] if column_index < len(headers) else ""
                label_attr = f' data-label="{html.escape(label, quote=True)}"' if label else ""
                parts.append(f"<td{span}{label_attr}>{html.escape(text)}</td>")
                column_index += max(1, colspan)
            parts.append("</tr>")
        parts.append("</tbody>")
    parts.append("</table></div>")
    return "".join(parts)


def _replace_tables(raw: str, tokens: dict[str, str]) -> str:
    """Replace tabular/longtable environments without leaking column specs."""
    begin_re = re.compile(r"\\begin\{(longtable|tabular\*?|tabularx|tabulary)\}")
    cursor = 0
    result: list[str] = []
    while True:
        match = begin_re.search(raw, cursor)
        if not match:
            result.append(raw[cursor:])
            break
        env = match.group(1)
        end_marker = f"\\end{{{env}}}"
        end = raw.find(end_marker, match.end())
        if end < 0:
            # Hide the malformed begin declaration rather than dumping a TeX
            # column specification into player-visible prose.
            result.append(raw[cursor:match.start()])
            result.append("\n<div class=\"missing-asset\">Unclosed LaTeX table (see source)</div>\n")
            cursor = match.end()
            continue
        pos = match.end()
        _, option_end = _extract_bracketed(raw, pos)
        if option_end != pos:
            pos = option_end
        # tabular* / tabularx / tabulary take width + column specification.
        argument_count = 2 if env in {"tabular*", "tabularx", "tabulary"} else 1
        for _ in range(argument_count):
            arg, next_pos = _extract_braced(raw, pos)
            if arg is None:
                break
            pos = next_pos
        content = raw[pos:end]
        token = f"@@LOREFORGE_TABLE_{len(tokens)}@@"
        tokens[token] = _table_to_html(env, content)
        result.append(raw[cursor:match.start()])
        result.append(token)
        cursor = end + len(end_marker)
    joined = "".join(result)
    # Common wrappers around tables should not appear as text after tokenizing.
    joined = re.sub(r"\\resizebox\s*\{[^{}]*\}\s*\{[^{}]*\}\s*\{\s*(@@LOREFORGE_TABLE_\d+@@)\s*\}", r"\1", joined, flags=re.DOTALL)
    joined = re.sub(r"\\adjustbox\s*\{[^{}]*\}\s*\{\s*(@@LOREFORGE_TABLE_\d+@@)\s*\}", r"\1", joined, flags=re.DOTALL)
    return joined


def _image_classes_and_style(options: str, ref: str, *, entity_portrait: bool = False, overlay_art: bool = False) -> tuple[str, str]:
    options = options or ""
    classes = ["lore-image"]
    style_parts: list[str] = []
    lower_ref = ref.replace("\\", "/").lower()
    width_match = re.search(r"width\s*=\s*([0-9.]+)?\s*\\(paperwidth|textwidth|linewidth|columnwidth)", options)
    scale_match = re.search(r"(?:^|,)\s*scale\s*=\s*([0-9.]+)", options)
    if width_match:
        factor = float(width_match.group(1)) if width_match.group(1) else 1.0
        basis = width_match.group(2)
        if factor < 0.98:
            style_parts.append(f"--image-width:{max(10, min(100, factor * 100)):.1f}%")
            classes.append("lore-image-sized")
        elif basis == "paperwidth":
            classes.append("lore-image-wide")
    elif scale_match:
        factor = max(.1, min(1.0, float(scale_match.group(1))))
        style_parts.append(f"--image-width:{factor * 100:.1f}%")
        classes.append("lore-image-sized")
    height_match = re.search(r"height\s*=\s*([0-9.]+)?\s*\\(paperheight|textheight|linewidth|columnwidth)", options)
    if height_match:
        factor = float(height_match.group(1)) if height_match.group(1) else 1.0
        style_parts.append(f"--image-max-height:{max(20, min(95, factor * 100)):.1f}vh")
    if "angle=" in options:
        angle = re.search(r"angle\s*=\s*(-?[0-9.]+)", options)
        if angle:
            style_parts.append(f"--image-rotation:{float(angle.group(1)):.2f}deg")
            classes.append("lore-image-rotated")
    if any(segment in lower_ref for segment in ("/npcs/", "/characters/", "/people/", "/portraits/")):
        classes.append("lore-image-character")
    if overlay_art:
        classes.append("lore-image-overlay-art")
    if entity_portrait:
        classes.extend(["lore-image-character", "lore-entity-portrait"])
        # PDF page-width positioning should not force a web portrait to full bleed.
        classes = [c for c in classes if c != "lore-image-wide"]
        style_parts = [part for part in style_parts if not part.startswith("--image-width:")]
    return " ".join(dict.fromkeys(classes)), ";".join(style_parts)


def _profile_block_to_html(content: str) -> str | None:
    """Turn a ``multicols`` label/value profile into a compact semantic grid."""
    rows = re.split(r"(?<!\\)\\\\(?:\[[^\]]*\])?", content)
    items: list[tuple[str, str]] = []
    for row in rows:
        row = row.strip()
        if not row:
            continue
        match = re.match(r"\\textbf\s*\{([^{}]+)\}\s*(.*)$", row, flags=re.DOTALL)
        if not match:
            return None
        label = clean_inline_text(match.group(1)).rstrip(":").strip()
        value = clean_inline_text(match.group(2)).strip()
        if not label:
            return None
        items.append((label, value))
    if len(items) < 3:
        return None
    parts = ['<dl class="lore-profile-grid">']
    for label, value in items:
        parts.append(f'<div class="lore-profile-item"><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd></div>')
    parts.append('</dl>')
    return ''.join(parts)


def _parse_image_directive(value: str) -> dict:
    out: dict[str, str | float | bool] = {}
    try:
        parts = shlex.split(value, posix=True)
    except ValueError:
        parts = value.split()
    for part in parts:
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        key = key.strip().lower().replace("-", "_")
        raw_value = raw_value.strip().strip('"').strip("'")
        if key in {"layout", "frame", "caption", "blend"}:
            out[key] = raw_value
        elif key in {"width", "x", "y", "opacity"}:
            try:
                number = float(raw_value.rstrip("%"))
                if key == "opacity":
                    out[key] = max(0.05, min(1.0, number))
                else:
                    out[key] = max(0.0, min(100.0, number))
            except ValueError:
                pass
        elif key == "parallax":
            out[key] = raw_value.lower() in {"1", "true", "yes", "on"}
    layout = str(out.get("layout") or "auto").lower()
    if layout not in {"auto", "center", "left", "right", "wide", "fullbleed", "portrait", "banner", "breakout", "watermark", "edge-left", "edge-right"}:
        out["layout"] = "auto"
    frame = str(out.get("frame") or "simple").lower()
    if frame not in {"none", "simple", "ornate", "shadow"}:
        out["frame"] = "simple"
    blend = str(out.get("blend") or "normal").lower()
    if blend not in {"normal", "multiply", "screen", "soft-light", "overlay"}:
        out["blend"] = "normal"
    return out


def _parse_scene_directive(value: str) -> dict:
    out: dict[str, str | float | bool] = {
        "image": "", "opacity": 0.34, "x": 50.0, "y": 50.0,
        "tone": "dark", "min_height": 260.0, "parallax": False,
    }
    try:
        parts = shlex.split(value, posix=True)
    except ValueError:
        parts = value.split()
    for part in parts:
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        key = key.strip().lower().replace("-", "_")
        raw_value = raw_value.strip().strip('"').strip("'")
        if key in {"image", "tone"}:
            out[key] = raw_value
        elif key in {"opacity", "x", "y", "min_height"}:
            try:
                number = float(raw_value.rstrip("%px"))
            except ValueError:
                continue
            if key == "opacity":
                out[key] = max(0.0, min(0.85, number))
            elif key in {"x", "y"}:
                out[key] = max(0.0, min(100.0, number))
            else:
                out[key] = max(160.0, min(900.0, number))
        elif key == "parallax":
            out[key] = raw_value.lower() in {"1", "true", "yes", "on"}
    if str(out.get("tone") or "dark").lower() not in {"dark", "light", "sepia", "arcane", "mist", "blood"}:
        out["tone"] = "dark"
    return out


def latex_fragment_to_html(raw: str, settings: Settings, *, page_kind: str = "", analysis: dict | None = None, _allow_panels: bool = True) -> tuple[str, str]:
    # Loreforge image/panel directives are comments so they remain completely invisible
    # to TeX/Overleaf while giving the responsive wiki explicit layout intent.
    # Example: % loreforge-image: layout=right width=38 frame=ornate parallax=true
    # Scene panels are web-only wrappers around normal LaTeX prose. They let the
    # GM put a selected passage over atmospheric artwork without changing the PDF.
    tokens: dict[str, str] = {}
    if _allow_panels:
        panel_re = re.compile(
            r"(?ms)^[ \t]*%\s*loreforge-panel-start\s*:\s*([^\r\n]+)\r?\n(.*?)^[ \t]*%\s*loreforge-panel-end\s*$"
        )
        def panel_sub(m: re.Match) -> str:
            opts = _parse_scene_directive(m.group(1))
            inner_html, _ = latex_fragment_to_html(
                m.group(2), settings, page_kind=page_kind, analysis=analysis, _allow_panels=False
            )
            image_ref = str(opts.get("image") or "")
            url = presentation_asset_url(settings, image_ref) if image_ref.startswith(("project:", "upload:", "/project-asset/", "/uploads/")) else asset_url(settings, image_ref)
            token = f"@@LOREFORGE_SCENE_{len(tokens)}@@"
            tone = html.escape(str(opts.get("tone") or "dark"), quote=True)
            classes = f"lore-scene-panel tone-{tone}" + (" lore-scene-parallax" if opts.get("parallax") else "")
            style = (
                f"--scene-opacity:{float(opts.get('opacity', .34)):.3f};"
                f"--scene-x:{float(opts.get('x', 50)):.1f}%;"
                f"--scene-y:{float(opts.get('y', 50)):.1f}%;"
                f"--scene-min-height:{float(opts.get('min_height', 260)):.0f}px;"
            )
            if url:
                style += f"--scene-image:url('{html.escape(url, quote=True)}');"
            tokens[token] = f'<section class="{classes}" style="{style}"><div class="lore-scene-copy">{inner_html.replace(chr(10), "")}</div></section>'
            return "\n" + token + "\n"
        raw = panel_re.sub(panel_sub, raw)

    directive_values: dict[str, dict] = {}
    def protect_directive(m: re.Match) -> str:
        token = f"@@LOREFORGE_IMGDIR_{len(directive_values)}@@"
        directive_values[token] = _parse_image_directive(m.group(1))
        return token
    raw = re.sub(r"(?mi)^[ \t]*%\s*loreforge-image\s*:\s*([^\r\n]+)$", protect_directive, raw)

    # Remove ordinary comments and document-only commands while preserving content arguments.
    raw = "\n".join(strip_comments(x) for x in raw.splitlines())
    raw = re.sub(r"\\(?:label|index|cite|pageref|ref)\s*\{[^{}]*\}", "", raw)
    raw = re.sub(r"\\(?:vspace|hspace)\*?(?:\[[^\]]*\])?\s*\{[^{}]*\}", "", raw)

    # ------------------------------------------------------------------
    # Pathfinder 2e campaign semantics
    # ------------------------------------------------------------------
    # These are deliberately implemented as *renderers*, not hard-coded source
    # rewrites. The user's LaTeX definitions remain authoritative for the PDF,
    # while the wiki gets native, responsive PF2e cards/stat blocks.
    def stash(prefix: str, value: str) -> str:
        token = f"@@LOREFORGE_{prefix}_{len(tokens)}@@"
        tokens[token] = value
        return token

    def inner_html(value: str) -> str:
        rendered, _ = latex_fragment_to_html(
            value, settings, page_kind=page_kind, analysis=analysis, _allow_panels=False
        )
        rendered = rendered.strip()
        single = re.fullmatch(r"<p>(.*)</p>", rendered, flags=re.DOTALL)
        return single.group(1) if single else rendered

    action_symbol_specs = {
        "actionOne": ("Images/Symbols/oneaction.png", "One action", "1"),
        "actionTwo": ("Images/Symbols/twoaction.png", "Two actions", "2"),
        "actionThree": ("Images/Symbols/threeaction.png", "Three actions", "3"),
        "reaction": ("Images/Symbols/reaction.png", "Reaction", "R"),
        "freeAction": ("Images/Symbols/freeaction.png", "Free action", "F"),
    }

    def action_symbol_html(command: str) -> str:
        path, label, fallback = action_symbol_specs[command]
        url = asset_url(settings, path)
        if url:
            return (
                f'<span class="pf2-action-symbol pf2-action-{html.escape(command.lower(), quote=True)}" '
                f'title="{html.escape(label, quote=True)}"><img src="{html.escape(url, quote=True)}" '
                f'alt="{html.escape(label, quote=True)}"></span>'
            )
        return (
            f'<span class="pf2-action-symbol pf2-action-fallback" title="{html.escape(label, quote=True)}" '
            f'aria-label="{html.escape(label, quote=True)}">{html.escape(fallback)}</span>'
        )

    def render_rule_card(args: list[str], kind: str) -> str:
        title = inner_html(args[0])
        meta = inner_html(args[1])
        traits = inner_html(args[2])
        body = inner_html(args[3])
        if kind == "feat":
            right = f"Feat {meta}" if meta else "Feat"
            kicker = "FEAT"
        elif kind == "item":
            right = meta
            kicker = "ITEM"
        else:
            right = meta
            kicker = "ACTION"
        return (
            f'<section class="pf2-rule-card pf2-{kind}">'
            f'<div class="pf2-rule-kicker">{kicker}</div>'
            f'<header class="pf2-rule-header"><h3>{title}</h3><strong>{right}</strong></header>'
            f'{f"<div class=\"pf2-traits\">{traits}</div>" if traits else ""}'
            f'<div class="pf2-rule-divider"></div><div class="pf2-rule-body">{body}</div>'
            f'</section>'
        )

    for command, kind in (("feat", "feat"), ("action", "action"), ("itemtemplate", "item")):
        raw = _replace_balanced_command(
            raw, command, 4,
            lambda args, kind=kind: "\n" + stash("PF2RULE", render_rule_card(args, kind)) + "\n",
        )

    def render_monster(args: list[str], body: str) -> str:
        name, level, traits, source = [inner_html(x) for x in args]
        body_html, _ = latex_fragment_to_html(
            body, settings, page_kind=page_kind, analysis=analysis, _allow_panels=False
        )
        source_line = f'<div class="pf2-monster-source">{source}</div>' if clean_inline_text(args[3]) else ""
        return (
            '<section class="pf2-statblock pf2-monster">'
            '<div class="pf2-stat-ornament" aria-hidden="true"></div>'
            f'<header class="pf2-monster-header"><h3>{name}</h3><strong>Creature {level}</strong></header>'
            f'{f"<div class=\"pf2-traits\">{traits}</div>" if traits else ""}'
            f'{source_line}<div class="pf2-stat-rule"></div>'
            f'<div class="pf2-stat-body">{body_html}</div>'
            '</section>'
        )

    raw = _replace_balanced_environment(
        raw, "monster", 4,
        lambda args, body: "\n" + stash("PF2MONSTER", render_monster(args, body)) + "\n",
    )

    def stat_line(label: str, value: str, extra_class: str = "") -> str:
        return (
            f'<div class="pf2-stat-line {extra_class}"><strong>{inner_html(label)}</strong>'
            f'<span>{inner_html(value)}</span></div>'
        )

    raw = _replace_balanced_command(raw, "monstersection", 1, lambda a: "\n" + stash("PF2STAT", f'<div class="pf2-stat-section"><span>{inner_html(a[0])}</span></div>') + "\n")
    raw = _replace_balanced_command(raw, "monsterline", 2, lambda a: "\n" + stash("PF2STAT", stat_line(a[0], a[1])) + "\n")
    raw = _replace_balanced_command(
        raw, "monsterabilityscores", 6,
        lambda a: "\n" + stash("PF2STAT", '<div class="pf2-ability-grid">' + ''.join(
            f'<div><strong>{name}</strong><span>{inner_html(value)}</span></div>'
            for name, value in zip(("Str", "Dex", "Con", "Int", "Wis", "Cha"), a)
        ) + '</div>') + "\n",
    )
    raw = _replace_balanced_command(
        raw, "monsterdefenses", 4,
        lambda a: "\n" + stash("PF2STAT", (
            '<div class="pf2-defense-block">'
            f'<div><strong>AC</strong> {inner_html(a[0])}; <strong>Saves</strong> {inner_html(a[1])}</div>'
            f'<div>{inner_html(a[2])}</div><div>{inner_html(a[3])}</div>'
            '</div>'
        )) + "\n",
    )
    raw = _replace_balanced_command(raw, "monsterspeed", 1, lambda a: "\n" + stash("PF2STAT", stat_line("Speed", a[0])) + "\n")

    def render_attack(a: list[str]) -> str:
        bonus_text = clean_inline_text(a[1]).strip()
        bonus = bonus_text if bonus_text.startswith(("+", "-")) else ("+" + bonus_text if bonus_text else "")
        traits = inner_html(a[2])
        return (
            '<div class="pf2-stat-line pf2-attack-line">'
            f'<strong>{inner_html(a[0])}</strong><span>{html.escape(bonus)}'
            f'{f" <em>{traits}</em>" if traits else ""}, <b>Damage</b> {inner_html(a[3])}</span></div>'
        )
    raw = _replace_balanced_command(raw, "monsterattack", 4, lambda a: "\n" + stash("PF2STAT", render_attack(a)) + "\n")
    raw = _replace_balanced_command(
        raw, "monsterspellcasting", 4,
        lambda a: "\n" + stash("PF2STAT", (
            '<div class="pf2-spellcasting">'
            f'<div><strong>{inner_html(a[0])}</strong> {inner_html(a[1])}</div>'
            f'<div>{inner_html(a[2])}</div>'
            f'{f"<div class=\"pf2-stat-note\">{inner_html(a[3])}</div>" if clean_inline_text(a[3]) else ""}'
            '</div>'
        )) + "\n",
    )
    raw = _replace_balanced_command(
        raw, "monsterability", 2,
        lambda a: "\n" + stash("PF2STAT", f'<div class="pf2-monster-ability"><strong>{inner_html(a[0])}</strong><span>{inner_html(a[1])}</span></div>') + "\n",
    )

    # The user's legacy \image{width}{path} helper now behaves like a native
    # Loreforge image on the wiki while remaining untouched for TeX itself.
    def render_custom_image(a: list[str]) -> str:
        width_raw, ref = a[0].strip(), a[1].strip()
        url = asset_url(settings, ref)
        if not url:
            return f'<div class="missing-asset">Missing image: {html.escape(ref)}</div>'
        width_pct = 78.0
        wm = re.search(r"([0-9]*\.?[0-9]+)\s*\\(?:textwidth|linewidth|columnwidth|paperwidth)", width_raw)
        if wm:
            width_pct = max(15.0, min(100.0, float(wm.group(1)) * 100.0))
        alt = Path(ref).stem.replace("_", " ").replace("-", " ")
        return (
            f'<figure class="lore-image lore-image-custom lore-image-sized" style="--image-width:{width_pct:.1f}%">'
            f'<button class="lore-image-zoom" type="button" aria-label="Open {html.escape(alt, quote=True)}">'
            f'<img loading="lazy" decoding="async" src="{html.escape(url, quote=True)}" alt="{html.escape(alt, quote=True)}"></button>'
            '</figure>'
        )
    raw = _replace_balanced_command(raw, "image", 2, lambda a: "\n" + stash("CUSTOMIMAGE", render_custom_image(a)) + "\n")

    # Zero-argument PF2e action symbols are rendered last so they also work in
    # ordinary prose. Calls inside feat/action/monster arguments are handled by
    # the recursive renderers above.
    for command in action_symbol_specs:
        raw = re.sub(
            r"\\" + re.escape(command) + r"\b",
            lambda _m, command=command: stash("ACTIONICON", action_symbol_html(command)),
            raw,
        )

    # Protect images with tokens before generic macro cleanup.  On Person of
    # Note pages, the first NPC/overlay image becomes responsive portrait art
    # rather than retaining PDF-specific TikZ page positioning.
    entity_portrait_token: str | None = None
    source_before_images = raw
    def image_sub(m: re.Match) -> str:
        nonlocal entity_portrait_token
        options = m.group(1) or ""
        ref = m.group(2)
        url = asset_url(settings, ref)
        token = f"@@LOREFORGE_IMAGE_{len(tokens)}@@"

        # A protected Loreforge comment immediately before an image overrides
        # heuristic web placement without changing the PDF source semantics.
        prefix = source_before_images[:m.start()]
        directive = {}
        directive_token = ""
        best_pos = -1
        for candidate, value in directive_values.items():
            pos = prefix.rfind(candidate)
            if pos > best_pos and m.start() - pos < 1800:
                best_pos = pos
                directive_token = candidate
                directive = value

        context = source_before_images[max(0, m.start() - 650):m.start()].lower()
        overlay_art = "\\begin{tikzpicture" in context and "\\end{tikzpicture" not in context.rsplit("\\begin{tikzpicture", 1)[-1]
        wrap_side = None
        wrap_match = re.search(r"\\begin\{wrapfigure\}\s*\{([rlio])\}", context)
        if wrap_match and "\\end{wrapfigure" not in context.rsplit("\\begin{wrapfigure", 1)[-1]:
            wrap_side = "right" if wrap_match.group(1) in {"r", "o"} else "left"
        layout = str(directive.get("layout") or "auto").lower()
        lower_ref = ref.replace("\\", "/").lower()
        looks_like_character = any(segment in lower_ref for segment in ("/npcs/", "/characters/", "/people/", "/portraits/"))
        allow_auto_portrait = layout in {"auto", "portrait"}
        entity_portrait = page_kind == "entity" and entity_portrait_token is None and allow_auto_portrait and (looks_like_character or overlay_art or layout == "portrait")
        if entity_portrait:
            entity_portrait_token = token
        if url:
            caption = clean_inline_text(str(directive.get("caption") or Path(ref).stem.replace("_", " ")))
            classes, style = _image_classes_and_style(options, ref, entity_portrait=entity_portrait, overlay_art=overlay_art)
            style_parts = [part for part in style.split(";") if part]
            if layout != "auto":
                classes += f" lore-image-layout-{layout}"
            elif wrap_side and not entity_portrait:
                classes += f" lore-image-float-{wrap_side}"
            frame = str(directive.get("frame") or "simple").lower()
            classes += f" lore-image-frame-{frame}"
            if directive.get("parallax"):
                classes += " lore-image-parallax"
            if "opacity" in directive:
                style_parts.append(f"--image-opacity:{float(directive['opacity']):.3f}")
            blend = str(directive.get("blend") or "normal").lower()
            if blend != "normal":
                classes += f" lore-image-blend-{blend}"
            if "width" in directive:
                style_parts = [part for part in style_parts if not part.startswith("--image-width:")]
                style_parts.append(f"--image-width:{float(directive['width']):.1f}%")
                classes += " lore-image-sized"
            if "x" in directive:
                style_parts.append(f"--image-focus-x:{float(directive['x']):.1f}%")
            if "y" in directive:
                style_parts.append(f"--image-focus-y:{float(directive['y']):.1f}%")
            style = ";".join(style_parts)
            style_attr = f' style="{html.escape(style, quote=True)}"' if style else ""
            directive_caption = directive.get("caption")
            figcaption = f'<figcaption>{html.escape(clean_inline_text(str(directive_caption)))}</figcaption>' if directive_caption else ""
            if Path(ref).suffix.lower() == ".pdf":
                tokens[token] = f'<figure class="{classes} lore-pdf-figure"{style_attr}><object data="{html.escape(url, quote=True)}" type="application/pdf"><a href="{html.escape(url, quote=True)}">Open {html.escape(caption)}</a></object>{figcaption}</figure>'
            else:
                tokens[token] = f'<figure class="{classes}"{style_attr}><button class="lore-image-zoom" type="button" aria-label="Open {html.escape(caption)}"><img loading="lazy" decoding="async" src="{html.escape(url, quote=True)}" alt="{html.escape(caption)}"></button>{figcaption}</figure>'
        else:
            tokens[token] = f'<div class="missing-asset">Missing image: {html.escape(ref)}</div>'
        return token
    raw = IMAGE_RE.sub(image_sub, raw)
    for directive_token in directive_values:
        raw = raw.replace(directive_token, "")

    # Consume table environments before generic command cleanup.  Otherwise
    # LaTeX column declarations such as >{\\raggedright}p{3.5cm} are treated as
    # ordinary prose, which is exactly the artifact visible in the screenshot.
    raw = _replace_tables(raw, tokens)

    # TikZ overlay blocks are a common way to pin character art to the bottom
    # of a PDF page.  The positioning instructions have no useful web meaning;
    # retain embedded image tokens and discard the page-coordinate machinery.
    raw = re.sub(
        r"\\node(?:\[[^\]]*\])?\s*(?:at\s*\([^)]*\))?\s*\{\s*(@@LOREFORGE_IMAGE_\d+@@)\s*\}\s*;?",
        r"\1",
        raw,
        flags=re.DOTALL,
    )
    raw = re.sub(r"\\begin\{tikzpicture\}(?:\[[^\]]*\])?", "", raw)
    raw = re.sub(r"\\end\{tikzpicture\}", "", raw)
    raw = re.sub(r"\\(?:newpage|clearpage|pagebreak|nopagebreak)\*?(?:\[[^\]]*\])?", "\n", raw)
    if page_kind == "entity" and entity_portrait_token and entity_portrait_token in raw:
        raw = raw.replace(entity_portrait_token, "", 1)
        raw = entity_portrait_token + "\n" + raw

    # Figure wrappers are layout containers in LaTeX.  Keep the image and a
    # readable caption, but allow the responsive site to choose positioning.
    raw = re.sub(r"\\begin\{figure\*?\}(?:\[[^\]]*\])?", "\n", raw)
    raw = re.sub(r"\\end\{figure\*?\}", "\n", raw)
    raw = re.sub(r"\\begin\{wrapfigure\}\s*\{[^{}]*\}\s*\{[^{}]*\}", "\n", raw)
    raw = re.sub(r"\\end\{wrapfigure\}", "\n", raw)
    def caption_sub(m: re.Match) -> str:
        token = f"@@LOREFORGE_CAPTION_{len(tokens)}@@"
        tokens[token] = f'<div class="lore-image-caption">{html.escape(clean_inline_text(m.group(1)))}</div>'
        return token
    raw = re.sub(r"\\caption(?:\[[^\]]*\])?\s*\{([^{}]*)\}", caption_sub, raw)
    # Layout-only wrappers that are meaningful on paper but should never leak
    # into responsive prose.
    raw = re.sub(r"\\begin\{(?:center|flushleft|flushright|adjustbox)\}(?:\{[^{}]*\})?", "\n", raw)
    raw = re.sub(r"\\end\{(?:center|flushleft|flushright|adjustbox)\}", "\n", raw)
    raw = re.sub(r"\\(?:centering|raggedright|raggedleft|small|footnotesize|scriptsize|tiny|normalsize)\b", "", raw)

    # Multi-column blocks become a semantic profile grid when they consist of
    # bold label/value lines (the common \pon Profile pattern); otherwise they
    # remain genuine responsive columns.
    def multicol_sub(m: re.Match) -> str:
        count, content = m.group(1), m.group(2)
        if page_kind == "entity":
            profile_html = _profile_block_to_html(content)
            if profile_html:
                token = f"@@LOREFORGE_PROFILE_{len(tokens)}@@"
                tokens[token] = profile_html
                return f"\n{token}\n"
        return f"\n@@COL_START_{count}@@\n{content}\n@@COL_END@@\n"
    raw = re.sub(r"\\begin\{multicols\}\s*\{([1-4])\}(.*?)\\end\{multicols\}", multicol_sub, raw, flags=re.DOTALL)

    # Convert simple environments to markdown-ish sentinels.
    raw = re.sub(r"\\begin\{(?:itemize|description)\}", "\n@@UL_START@@\n", raw)
    raw = re.sub(r"\\end\{(?:itemize|description)\}", "\n@@UL_END@@\n", raw)
    raw = re.sub(r"\\begin\{enumerate\}", "\n@@OL_START@@\n", raw)
    raw = re.sub(r"\\end\{enumerate\}", "\n@@OL_END@@\n", raw)
    raw = re.sub(r"\\begin\{(?:quote|quotation)\}", "\n@@QUOTE_START@@\n", raw)
    raw = re.sub(r"\\end\{(?:quote|quotation)\}", "\n@@QUOTE_END@@\n", raw)
    raw = re.sub(r"\\item(?:\[[^\]]*\])?", "\n@@ITEM@@ ", raw)

    # Headings that remain inside a wiki article.  A page title is already H1,
    # so LaTeX section/subsection/subsubsection map naturally to H2/H3/H4.
    raw = re.sub(r"\\section\*?\s*\{([^{}]+)\}", lambda m: f"\n@@H2@@{clean_inline_text(m.group(1))}\n", raw)
    raw = re.sub(r"\\subsection\*?\s*\{([^{}]+)\}", lambda m: f"\n@@H3@@{clean_inline_text(m.group(1))}\n", raw)
    raw = re.sub(r"\\subsubsection\*?\s*\{([^{}]+)\}", lambda m: f"\n@@H4@@{clean_inline_text(m.group(1))}\n", raw)
    raw = re.sub(r"\\paragraph\*?\s*\{([^{}]+)\}", lambda m: f"\n@@H4@@{clean_inline_text(m.group(1))}\n", raw)

    # Inline semantic macros -> tokens.
    patterns = [
        (r"\\textbf\s*\{([^{}]*)\}", "strong"),
        (r"\\(?:textit|emph)\s*\{([^{}]*)\}", "em"),
        (r"\\underline\s*\{([^{}]*)\}", "u"),
        (r"\\texttt\s*\{([^{}]*)\}", "code"),
    ]
    for pattern, tag in patterns:
        def sub(m: re.Match, tag=tag) -> str:
            token = f"@@LOREFORGE_INLINE_{len(tokens)}@@"
            tokens[token] = f"<{tag}>{html.escape(clean_inline_text(m.group(1)))}</{tag}>"
            return token
        for _ in range(4):
            raw = re.sub(pattern, sub, raw)

    def href_sub(m: re.Match) -> str:
        url, label = m.group(1), clean_inline_text(m.group(2))
        safe = url if re.match(r"^https?://", url) else "#"
        token = f"@@LOREFORGE_LINK_{len(tokens)}@@"
        tokens[token] = f'<a href="{html.escape(safe, quote=True)}" target="_blank" rel="noopener">{html.escape(label)}</a>'
        return token
    raw = re.sub(r"\\href\s*\{([^{}]+)\}\s*\{([^{}]+)\}", href_sub, raw)

    def wiki_sub(m: re.Match) -> str:
        target = clean_inline_text(m.group(1)); label = clean_inline_text(m.group(2) or target)
        token = f"@@LOREFORGE_WIKI_{len(tokens)}@@"
        tokens[token] = f'<a class="wiki-link" href="/wiki/{slugify(target)}">{html.escape(label)}</a>'
        return token
    raw = re.sub(r"\\wiki\s*\{([^{}]+)\}(?:\s*\{([^{}]+)\})?", wiki_sub, raw)

    # Heuristic custom macros. Preserve up to eight balanced arguments instead
    # of relying on `[^{}]*`, so nested formatting in campaign-specific commands
    # survives even when Loreforge does not know that command's exact semantics.
    analysis_macros = {x["name"]: x for x in (analysis or analyze_project(settings)).get("custom_macros", [])}
    for name, info in analysis_macros.items():
        argc = int(info.get("args", 0) or 0)
        if argc <= 0 or argc > 8:
            continue
        def custom_balanced(args_raw: list[str], name=name, info=info) -> str:
            args = [clean_inline_text(x) for x in args_raw]
            token = f"@@LOREFORGE_CUSTOM_{len(tokens)}@@"
            kind = info["kind"]
            if kind in {"npc-card", "location-card", "callout"}:
                title = args[0] if args else name
                body = " · ".join(args[1:])
                tokens[token] = f'<aside class="lore-callout {kind}"><div class="callout-kicker">{html.escape(name)}</div><strong>{html.escape(title)}</strong>{f"<p>{html.escape(body)}</p>" if body else ""}</aside>'
            else:
                tokens[token] = html.escape(" ".join(args))
            return token
        raw = _replace_balanced_command(raw, name, argc, custom_balanced)

    # Common two/three-argument visual wrappers: keep the human-readable content, not the color name.
    raw = re.sub(r"\\textcolor\s*\{[^{}]*\}\s*\{([^{}]*)\}", r"\1", raw)
    raw = re.sub(r"\\colorbox\s*\{[^{}]*\}\s*\{([^{}]*)\}", r"\1", raw)
    raw = re.sub(r"\\fcolorbox\s*\{[^{}]*\}\s*\{[^{}]*\}\s*\{([^{}]*)\}", r"\1", raw)

    # Generic unknown commands: unwrap one text argument, then remove bare commands.
    for _ in range(6):
        raw = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?\s*\{([^{}]*)\}", r"\1", raw)
    raw = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", "", raw)
    raw = raw.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_").replace("~", " ")
    # Preserve explicit LaTeX line breaks.  In profile metadata `\\` is
    # semantic, not merely source formatting.
    br_token = f"@@LOREFORGE_BR_{len(tokens)}@@"
    tokens[br_token] = '<br class="tex-linebreak">'
    raw = raw.replace("\\\\", br_token + "\n")
    raw = raw.replace("{", "").replace("}", "")

    # Escape remaining prose while preserving tokens/sentinels.
    escaped = html.escape(raw)
    for token, value in tokens.items():
        escaped = escaped.replace(html.escape(token), value)
    for sentinel in ("UL_START", "UL_END", "OL_START", "OL_END", "QUOTE_START", "QUOTE_END", "ITEM", "H2", "H3", "H4", "COL_END"):
        escaped = escaped.replace(html.escape(f"@@{sentinel}@@"), f"@@{sentinel}@@")
    escaped = re.sub(r"@@COL_START_([1-4])@@", r"@@COL_START_\1@@", escaped)

    # Block formatter.
    lines = [x.rstrip() for x in escaped.splitlines()]
    out: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    quote_open = False
    column_open = False

    def flush_p() -> None:
        nonlocal paragraph
        text = " ".join(x.strip() for x in paragraph if x.strip()).strip()
        if text:
            out.append(f"<p>{text}</p>")
        paragraph = []

    for line in lines:
        s = line.strip()
        if not s:
            flush_p(); continue
        if s == "@@UL_START@@": flush_p(); out.append("<ul>"); list_kind = "ul"; continue
        if s == "@@UL_END@@": flush_p(); out.append("</ul>"); list_kind = None; continue
        if s == "@@OL_START@@": flush_p(); out.append("<ol>"); list_kind = "ol"; continue
        if s == "@@OL_END@@": flush_p(); out.append("</ol>"); list_kind = None; continue
        if s == "@@QUOTE_START@@": flush_p(); out.append("<blockquote>"); quote_open = True; continue
        if s == "@@QUOTE_END@@": flush_p(); out.append("</blockquote>"); quote_open = False; continue
        if s.startswith("@@ITEM@@"):
            flush_p(); out.append(f"<li>{s[len('@@ITEM@@'):].strip()}</li>"); continue
        if s.startswith("@@H2@@"): flush_p(); out.append(f"<h2>{s[len('@@H2@@'):]}</h2>"); continue
        if s.startswith("@@H3@@"): flush_p(); out.append(f"<h3>{s[len('@@H3@@'):]}</h3>"); continue
        if s.startswith("@@H4@@"): flush_p(); out.append(f"<h4>{s[len('@@H4@@'):]}</h4>"); continue
        if s.startswith("@@COL_START_"):
            flush_p()
            count = re.sub(r"\D", "", s) or "2"
            out.append(f'<div class="lore-columns lore-columns-{count}">')
            column_open = True
            continue
        if s == "@@COL_END@@":
            flush_p()
            if column_open:
                out.append("</div>")
                column_open = False
            continue
        if (s.startswith("<figure") or s.startswith("<aside") or s.startswith("<dl class=\"lore-profile-grid")
                or s.startswith("<div class=\"missing-asset") or s.startswith("<div class=\"lore-table-wrap")
                or s.startswith("<div class=\"lore-image-caption") or s.startswith("<section class=\"lore-scene-panel")
                or s.startswith("<section class=\"pf2-") or s.startswith("<div class=\"pf2-")
                or s.startswith("</section>")):
            flush_p(); out.append(s); continue
        paragraph.append(s)
    flush_p()
    if list_kind: out.append(f"</{list_kind}>")
    if quote_open: out.append("</blockquote>")
    if column_open: out.append("</div>")
    html_body = "\n".join(out)
    plain = re.sub(r"<[^>]+>", " ", html_body)
    plain = html.unescape(re.sub(r"\s+", " ", plain)).strip()
    return html_body, plain


def _purge_latexmk_state(main: Path) -> list[str]:
    """Remove only generated dependency/aux state that can trap latexmk in a failed cache."""
    removed: list[str] = []
    candidates = [
        main.with_suffix(".fdb_latexmk"), main.with_suffix(".fls"), main.with_suffix(".aux"),
        main.with_suffix(".out"), main.with_suffix(".toc"), main.with_suffix(".lof"),
        main.with_suffix(".lot"), main.with_suffix(".bcf"), main.with_name(main.stem + ".run.xml"),
        main.with_name(main.name + ".synctex.gz"),
    ]
    for path in candidates:
        try:
            if path.exists():
                path.unlink()
                removed.append(path.name)
        except OSError:
            pass
    return removed


def _observed_latex_engine(log: str) -> str:
    """Best-effort engine actually seen in TeX/latexmk output.

    This is intentionally based on engine banners rather than latexmk's selected
    mode. It lets Build Doctor distinguish "Loreforge chose XeLaTeX" from a
    project-local latexmk configuration that somehow launched pdfTeX anyway.
    """
    observations: list[tuple[int, str]] = []
    for pattern, engine in (
        (r"This is pdfTeX\b", "pdflatex"),
        (r"This is XeTeX\b", "xelatex"),
        (r"This is (?:LuaHBTeX|LuaTeX)\b", "lualatex"),
    ):
        for match in re.finditer(pattern, log or "", re.IGNORECASE):
            observations.append((match.start(), engine))
    return max(observations, default=(-1, ""))[1]


def _fontspec_pdftex_failure(log: str) -> bool:
    """Return True only for an explicit fontspec/pdfTeX incompatibility.

    The old detector used ``fontspec.*fatal`` with DOTALL, which could connect a
    harmless mention of fontspec near the top of a huge XeLaTeX log to an
    unrelated fatal error thousands of lines later. That produced the confusing
    "fontspec cannot run under pdfLaTeX" warning even while XeLaTeX was active.
    Keep this deliberately narrow.
    """
    text = log or ""
    explicit = (
        r"The fontspec package requires either XeTeX or LuaTeX",
        r"fontspec[^\n]{0,240}(?:cannot|can't|does not|doesn't)[^\n]{0,120}(?:pdfTeX|pdfLaTeX)",
        r"(?:pdfTeX|pdfLaTeX)[^\n]{0,180}(?:cannot|can't|incompatible)[^\n]{0,180}fontspec",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in explicit)


def _latex_failure_suggestions(log: str, effective_engine: str = "") -> list[str]:
    suggestions: list[str] = []
    missing = re.findall(r"(?:LaTeX Error|Package [^\n]+ Error): File [`']([^`']+)[`'] not found", log)
    if missing:
        names = ", ".join(dict.fromkeys(missing[:4]))
        suggestions.append(f"Missing LaTeX file/package: {names}. If it is a project .sty/.cls, upload it with the source; otherwise add the corresponding TeX Live package to the Dockerfile.")
    if "Option clash for package geometry" in log:
        suggestions.append("The geometry package is being loaded more than once with options. Keep one \\usepackage[...]{geometry}; after geometry is loaded, change later option changes to \\geometry{...}. This is a real source-level conflict, not a XeLaTeX problem.")
    if "There's no line here to end" in log:
        suggestions.append("One or more files use \\ where TeX is not inside a line/paragraph (often immediately after a heading, blank line, environment boundary, or custom block). Open the first reported line and remove that forced line break or replace it with paragraph spacing.")
    if "Missing number, treated as zero" in log:
        suggestions.append("TeX expected a numeric dimension but received something else. Check widths/heights, spacing lengths, and custom image calls around the first reported line (for example use 0.6\\textwidth rather than a bare 0.6 where a length is required).")
    if re.search(r"\\begin\{([^}]+)\}.*ended by \\end\{([^}]+)\}", log, re.IGNORECASE | re.DOTALL):
        suggestions.append("A LaTeX environment is unbalanced: a \\begin{...} is being closed by a different \\end{...}. Fix the first mismatch; many later errors can be cascading consequences.")
    if "Undefined control sequence" in log:
        suggestions.append("An undefined LaTeX command was encountered. Open the first file/line error below; this is often a missing package, misspelled macro, or a custom command definition file that was not imported/included.")
    if "Emergency stop" in log or "Fatal error occurred" in log:
        suggestions.append("TeX stopped fatally. The first error above the emergency-stop line is normally the real cause; later messages are often cascading errors.")
    if "shell escape" in log.lower() and ("disabled" in log.lower() or "restricted" in log.lower()):
        suggestions.append("This document appears to require shell escape. Only for a trusted private project, set LATEX_ALLOW_SHELL_ESCAPE=1 in Railway.")
    if re.search(r"File ended while scanning use of|Runaway argument", log):
        suggestions.append("TeX detected an unfinished argument/environment. Check for a missing }, \\end{...}, or unmatched custom macro near the first reported source line.")

    if re.search(r"Loreforge stopped this build stage after \d+s", log):
        suggestions.append("The LaTeX pipeline hit its time allowance, not a TeX syntax error. Loreforge now gives large XeLaTeX projects a longer adaptive build window and can finish a fresh XDV with xdvipdfmx as a separate stage.")
    if re.search(r"xdvipdfmx(?::fatal:|[^\n]*(?:error|failed))|No output PDF file written|XDV -> PDF stage", log, re.IGNORECASE):
        suggestions.append("XeLaTeX finished typesetting but PDF conversion failed. The blocking excerpt now shows xdvipdfmx's own message; this is usually an image/font embedding problem rather than a .tex syntax problem.")

    observed = _observed_latex_engine(log)
    effective = (effective_engine or "").lower()
    if effective in {"xelatex", "lualatex"} and observed == "pdflatex":
        suggestions.append(
            f"Loreforge selected {effective}, but the TeX log shows pdfTeX actually ran. A project-local latexmkrc/.latexmkrc or custom build rule may be overriding the engine; remove that override or make it use {effective}."
        )
    elif _fontspec_pdftex_failure(log):
        if effective in {"xelatex", "lualatex"}:
            suggestions.append(
                f"The log contains an explicit fontspec/pdfTeX incompatibility even though Loreforge selected {effective}. This usually means a nested/custom build rule is invoking pdfLaTeX; inspect any latexmkrc/.latexmkrc or custom build command in the project."
            )
        else:
            suggestions.append("This project uses fontspec, which cannot run under pdfLaTeX. Loreforge normally auto-switches such projects to XeLaTeX; set LATEX_ENGINE=auto (recommended) or xelatex if you have explicitly overridden the engine.")
    else:
        # Only call this a missing-font problem when the log actually says the
        # requested font cannot be found. A generic fontspec package error is not
        # sufficient evidence.
        font_match = re.search(r"The font [\"`']([^\"`']+)[\"`'][^\n]{0,260}(?:cannot be found|not found)", log, re.IGNORECASE)
        if not font_match:
            font_match = re.search(r"font(?:spec)?[^\n]{0,120}[\"`']([^\"`']+)[\"`'][^\n]{0,180}(?:cannot be found|not found)", log, re.IGNORECASE)
        if font_match:
            suggestions.append(f"A requested font ({font_match.group(1)}) is unavailable. Loreforge includes TeX Gyre and EB Garamond in the Docker image; other project fonts can be supplied as .otf/.ttf files and referenced by file/path in fontspec.")
    if ("Nothing to do" in log or "All targets" in log) and "gave an error" in log:
        suggestions.append("latexmk had cached a previous failed run. Loreforge automatically clears its dependency state and retries in this build.")
    if not suggestions:
        suggestions.append("No specific TeX diagnosis was detected. Use FIRST BLOCKING ERROR above; Loreforge has appended the underlying engine .log when available.")
    return suggestions[:5]


def _attach_source_context(errors: list[dict], project_root: Path, radius: int = 1) -> list[dict]:
    """Attach a small source excerpt to clickable diagnostics.

    TeX logs are often cryptic; seeing the exact line next to the diagnostic makes
    imported projects dramatically faster to repair. This is read-only and never
    changes the campaign source.
    """
    cache: dict[str, list[str]] = {}
    by_name: dict[str, list[Path]] = {}
    try:
        for path in project_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".tex", ".sty", ".cls", ".bib"}:
                by_name.setdefault(path.name, []).append(path)
    except OSError:
        return errors
    for error in errors:
        name = error.get("file")
        line_no = error.get("line")
        if not name or not line_no or name not in by_name:
            continue
        path = by_name[name][0]
        key = str(path)
        if key not in cache:
            try:
                cache[key] = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
        lines = cache[key]
        idx = max(0, int(line_no) - 1)
        start = max(0, idx - radius)
        end = min(len(lines), idx + radius + 1)
        excerpt = []
        for i in range(start, end):
            marker = "›" if i == idx else " "
            excerpt.append(f"{marker} {i + 1}: {lines[i]}")
        error["source"] = "\n".join(excerpt)
        try:
            error["path"] = path.relative_to(project_root).as_posix()
        except ValueError:
            pass
    return errors



def _split_latex_options(raw: str) -> list[str]:
    """Split a LaTeX option list on top-level commas.

    Geometry options occasionally contain braces, so a plain ``str.split(',')``
    can corrupt otherwise valid settings. This intentionally handles just the
    brace/bracket nesting needed by package option lists.
    """
    out: list[str] = []
    start = 0
    brace = bracket = paren = 0
    for i, ch in enumerate(raw):
        if ch == "{" : brace += 1
        elif ch == "}" and brace: brace -= 1
        elif ch == "[" : bracket += 1
        elif ch == "]" and bracket: bracket -= 1
        elif ch == "(" : paren += 1
        elif ch == ")" and paren: paren -= 1
        elif ch == "," and brace == bracket == paren == 0:
            item = raw[start:i].strip()
            if item: out.append(item)
            start = i + 1
    item = raw[start:].strip()
    if item: out.append(item)
    return out


def _merged_geometry_options(declarations: list[dict]) -> str:
    """Merge repeated geometry option lists with later keyed values winning."""
    order: list[str] = []
    values: dict[str, str] = {}
    for decl in declarations:
        for option in _split_latex_options(str(decl.get("options") or "")):
            key = option.split("=", 1)[0].strip().lower() if "=" in option else option.strip().lower()
            if not key:
                continue
            if key not in values:
                order.append(key)
            values[key] = option
    return ",".join(values[k] for k in order if k in values)


def _geometry_declarations(lines: list[str]) -> list[dict]:
    r"""Return active dedicated ``\usepackage{geometry}`` declarations."""
    found: list[dict] = []
    rx = re.compile(r"^(\s*)\\usepackage(?:\[([^\]]*)\])?\{geometry\}(\s*(?:%.*)?)$")
    for i, line in enumerate(lines):
        if line.lstrip().startswith("%"):
            continue
        m = rx.match(line)
        if m:
            found.append({"line": i + 1, "indent": m.group(1), "options": m.group(2) or "", "expected": line})
    return found


def _geometry_consolidation_fix(rel: str, lines: list[str]) -> dict | None:
    r"""Build a reversible multi-line fix for duplicate geometry package loads.

    Repeated ``\usepackage[...]{geometry}`` declarations are a common Overleaf
    import problem.  The safe general form is to load the package without options
    once and then apply the merged layout with ``\geometry{...}``.  This also
    works when a class/package has already loaded geometry.  Later keyed values
    win, matching the author's apparent intent when declarations were repeated.
    """
    declarations = _geometry_declarations(lines)
    if len(declarations) < 2:
        return None
    merged = _merged_geometry_options(declarations)
    edits: list[dict] = []
    first = declarations[0]
    first_repl = f"{first['indent']}\\usepackage{{geometry}}"
    if merged:
        first_repl += f"\\geometry{{{merged}}}"
    edits.append({"path": rel, "line": first["line"], "expected": first["expected"], "replacement": first_repl})
    for decl in declarations[1:]:
        indent = decl["indent"]
        original = decl["expected"].strip()
        edits.append({
            "path": rel, "line": decl["line"], "expected": decl["expected"],
            "replacement": f"{indent}% Loreforge consolidated duplicate geometry declaration: {original}",
        })
    label = "Consolidate geometry settings"
    if merged:
        label += f" ({merged})"
    return {
        "path": rel, "line": first["line"], "label": label,
        "reason": "geometry was loaded repeatedly with options; Loreforge keeps one package load and applies merged options with later values winning.",
        "edits": edits,
    }


def _attach_quick_fixes(errors: list[dict], project_root: Path) -> list[dict]:
    """Attach conservative, revision-safe repairs to common TeX errors.

    Most fixes are one-line edits.  A few well-defined project repairs (such as
    duplicate geometry declarations) contain several verified edits.  The UI
    still requires an explicit GM click, and the backend verifies every source
    line before changing anything.
    """
    cache: dict[str, list[str]] = {}
    geometry_offered: set[str] = set()
    for error in errors:
        rel = error.get("path") or error.get("file")
        line_no = error.get("line")
        if not rel or not line_no:
            continue
        path = (project_root / rel).resolve()
        try:
            path.relative_to(project_root.resolve())
        except ValueError:
            continue
        if not path.exists() or not path.is_file():
            continue
        key = str(path)
        if key not in cache:
            try:
                cache[key] = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
        lines = cache[key]
        idx = max(0, min(len(lines)-1, int(line_no)-1)) if lines else 0
        message = str(error.get("message") or "")

        if "Option clash for package geometry" in message and rel not in geometry_offered:
            geo_fix = _geometry_consolidation_fix(rel, lines)
            if geo_fix:
                error["quick_fix"] = geo_fix
                geometry_offered.add(rel)

        def offer(i: int, replacement: str, label: str, reason: str) -> None:
            if i < 0 or i >= len(lines):
                return
            error["quick_fix"] = {
                "path": rel, "line": i + 1, "expected": lines[i],
                "replacement": replacement, "label": label, "reason": reason,
            }

        # TeX frequently reports the following line, so inspect both the reported
        # line and its predecessor for an impossible forced line break.
        if "There's no line here to end" in message:
            for i in (idx, idx-1):
                if i < 0 or i >= len(lines):
                    continue
                old = lines[i]
                stripped = old.strip()
                heading_or_boundary = (
                    re.match(r"^\\(?:section|subsection|subsubsection|chapter|part)\*?\{.*\}\s*\\\\\s*(?:%.*)?$", stripped)
                    or re.match(r"^\\begin\{multicols\}\{[1-4]\}\s*\\\\\s*(?:%.*)?$", stripped)
                    or re.match(r"^\\\\\s*(?:%.*)?$", stripped)
                )
                if heading_or_boundary:
                    replacement = re.sub(r"\s*\\\\\s*(?=(?:%.*)?$)", " ", old).rstrip()
                    offer(i, replacement, "Remove invalid line break", "A heading/environment boundary cannot be followed by \\ before a paragraph exists.")
                    break

        if "Missing number, treated as zero" in message:
            for i in (idx-1, idx):
                if i < 0 or i >= len(lines):
                    continue
                old = lines[i]
                if re.match(r"^\s*\\begin\{multicols\}\s*(?:%.*)?$", old):
                    suffix = ""
                    if "%" in old:
                        prefix, comment = old.split("%", 1)
                        replacement = prefix.rstrip() + "{2} %" + comment
                    else:
                        replacement = old.rstrip() + "{2}"
                    offer(i, replacement, "Set multicols to 2 columns", "The multicols environment requires a mandatory column count such as {2}.")
                    break

        if "Undefined control sequence" in message:
            for i in (idx, idx-1):
                if i < 0 or i >= len(lines):
                    continue
                old = lines[i]
                if "\\subsubection" in old:
                    offer(i, old.replace("\\subsubection", "\\subsubsection"), "Fix \\subsubsection typo", "\\subsubection is not a LaTeX command; this is a high-confidence spelling correction.")
                    break
                if re.search(r"\\The\b", old):
                    offer(i, re.sub(r"\\The\b", "The", old, count=1), "Replace accidental \\The", "The line starts an ordinary sentence with \\The, which TeX interprets as an undefined command.")
                    break
    return errors

def _extract_failure_excerpt(log: str, *, before: int = 3, after: int = 10) -> str:
    """Return a compact excerpt around the first genuinely blocking TeX error.

    TeX/latexmk output is not consistent enough for every failure to become a
    clickable ``file.tex:line`` diagnostic.  This fallback deliberately favors
    engine/package errors, runaway arguments, emergency stops, and classic
    ``! ...`` diagnostics over latexmk wrapper chatter so the GM always sees an
    actionable reason for a red build.
    """
    if not log:
        return ""
    lines = log.splitlines()
    strong = [
        re.compile(r"^.+\.(?:tex|sty|cls|bib):\d+:\s*(?:LaTeX|Package|Class|Font|Undefined|Missing|Extra|Runaway|Emergency|Fatal|Incomplete|File ended|Paragraph ended|Illegal|Misplaced|Use of).*", re.I),
        re.compile(r"^!\s+.+"),
        re.compile(r"(?:Emergency stop|Fatal error occurred|Runaway argument|File ended while scanning use of|Incomplete \\if|Undefined control sequence|Missing number, treated as zero|There's no line here to end|Option clash for package|LaTeX Error: File .* not found|Loreforge stopped this build stage after \d+s|xdvipdfmx:fatal:|No output PDF file written|Image inclusion failed)", re.I),
    ]
    # Search each diagnostic/engine section in chronological order, skipping
    # latexmk's generic collected-error summary where possible.
    candidates: list[int] = []
    for i, line in enumerate(lines):
        text = line.strip()
        if not text or "gave an error" in text.lower():
            continue
        if any(rx.search(text) for rx in strong):
            candidates.append(i)
    if not candidates:
        # Last-resort tail: enough context to reveal the command/package that
        # terminated even for an unfamiliar TeX error format.
        tail = [x for x in lines[-30:] if x.strip()]
        return "\n".join(tail[-18:]).strip()
    i = candidates[0]
    start = max(0, i - before)
    # Classic TeX logs often print the active input file immediately before the
    # `! Error`. Prefer that boundary over unrelated latexmk wrapper chatter.
    for j in range(i - 1, start - 1, -1):
        if re.search(r"\((?:\./)?[^()\s]+\.(?:tex|sty|cls)\b", lines[j], re.IGNORECASE):
            start = j
            break
    end = min(len(lines), i + after + 1)
    excerpt = lines[start:end]
    # Trim giant blank runs without altering the diagnostic text itself.
    out: list[str] = []
    blank = False
    for line in excerpt:
        if not line.strip():
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(line.rstrip())
            blank = False
    return "\n".join(out).strip()


def compile_pdf(settings: Settings, main_file: str | None = None, *, clean: bool = False) -> BuildResult:
    """Compile the source PDF and self-heal the common stale-latexmk failure mode.

    A failed latexmk run can leave ``.fdb_latexmk`` recording the engine as failed.
    A later invocation may then say both "Nothing to do" and "pdflatex: gave an
    error" without rerunning TeX. Loreforge detects that state, removes only
    generated dependency/auxiliary files, and retries automatically. If latexmk
    still fails without useful diagnostics, the underlying engine is invoked once
    directly so the editor receives the real TeX error rather than a one-line
    wrapper summary.
    """
    main_rel = main_file or choose_main(settings)
    main = safe_project_path(settings, main_rel)
    if not main.exists():
        raise ValueError(f"Main file not found: {main_rel}")
    engine, engine_recovery = _effective_latex_engine(settings)
    latexmk = shutil.which("latexmk")
    shell = "-shell-escape" if settings.allow_shell_escape else "-no-shell-escape"
    env = os.environ.copy()
    env.setdefault("openin_any", "p")
    env.setdefault("openout_any", "p")
    started = time.perf_counter()
    pdf = main.with_suffix(".pdf")
    xdv = main.with_suffix(".xdv")
    pdf_mtime_before = pdf.stat().st_mtime_ns if pdf.exists() else None
    xdv_mtime_before = xdv.stat().st_mtime_ns if xdv.exists() else None
    recovery_steps: list[str] = []
    if engine_recovery:
        recovery_steps.append(engine_recovery)

    # Remember the effective engine instead of treating AUTO -> XeLaTeX as a
    # fresh engine switch on every compile.  Repeatedly deleting .aux/.toc/.fdb
    # files made large imported books start from scratch every single time and
    # was a major cause of apparent compile failures/timeouts.
    last_engine = get_setting(settings, "last_effective_latex_engine", "").strip().lower()
    if last_engine != engine:
        removed = _purge_latexmk_state(main)
        if last_engine:
            recovery_steps.append(
                f"Build engine changed from {last_engine} to {engine}; cleared generated dependency state once: "
                + (", ".join(removed) if removed else "no stale state was present")
            )
        elif removed:
            recovery_steps.append(
                f"Initialized the {engine} build state and cleared pre-existing generated dependency files from the previous LaTeX engine state once: "
                + ", ".join(removed)
            )
        set_setting(settings, "last_effective_latex_engine", engine)

    # A 300+ page illustrated XeLaTeX book can legitimately need longer than
    # the historical 60 s default.  Scale the latexmk allowance for large
    # projects while keeping LATEX_TIMEOUT as the minimum user-configured value.
    try:
        tex_count = sum(1 for _ in settings.project_dir.rglob("*.tex"))
        image_count = sum(1 for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.pdf") for _ in settings.project_dir.rglob(pattern))
    except OSError:
        tex_count = image_count = 0
    large_project_timeout = 0
    if engine in {"xelatex", "lualatex"}:
        if tex_count >= 40 or image_count >= 80:
            large_project_timeout = 300
        elif tex_count >= 20 or image_count >= 30:
            large_project_timeout = 180
    compile_timeout = max(settings.latex_timeout, large_project_timeout)
    if compile_timeout > settings.latex_timeout:
        recovery_steps.append(
            f"Large XeLaTeX project detected ({tex_count} TeX files, {image_count} image/PDF assets); extended the per-stage build allowance from {settings.latex_timeout}s to {compile_timeout}s."
        )

    def run(cmd: list[str], timeout: int | None = None) -> tuple[int, str]:
        actual_timeout = timeout or compile_timeout
        try:
            proc = subprocess.run(
                cmd, cwd=main.parent, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=actual_timeout, env=env,
            )
            return proc.returncode, proc.stdout or ""
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return 124, str(output) + f"\nLoreforge stopped this build stage after {actual_timeout}s."

    command: list[str]
    if latexmk:
        mode = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}[engine]
        command = [latexmk, mode, "-g", "-interaction=nonstopmode", "-file-line-error", shell, main.name]
        if clean:
            clean_code, clean_log = run([latexmk, "-C", main.name], timeout=max(20, settings.latex_timeout // 2))
            removed = _purge_latexmk_state(main)
            recovery_steps.append("Manual clean build requested; generated LaTeX state was cleared.")
        code, log = run(command)
        stale_state = code != 0 and (
            ("Nothing to do" in log and "gave an error" in log)
            or ("All targets" in log and "gave an error" in log and "This is pdfTeX" not in log and "This is XeTeX" not in log and "This is Lua" not in log)
        )
        if stale_state:
            removed = _purge_latexmk_state(main)
            recovery_steps.append("Detected latexmk's cached failed-build state and removed: " + (", ".join(removed) if removed else "dependency cache"))
            retry_command = [latexmk, mode, "-gg", "-interaction=nonstopmode", "-file-line-error", shell, main.name]
            retry_code, retry_log = run(retry_command)
            log += "\n\n[Loreforge Build Doctor]\n" + recovery_steps[-1] + "\n\n[Clean retry]\n" + retry_log
            code = retry_code
            command = retry_command

        # XeLaTeX under latexmk intentionally writes an .xdv first and then
        # converts it with xdvipdfmx.  For very large illustrated books the old
        # outer timeout could fire after TeX had successfully produced hundreds
        # of pages but before that final conversion happened.  If we have a fresh
        # XDV, finish (or diagnostically repeat) the conversion as its own stage.
        if code != 0 and engine == "xelatex" and xdv.exists() and not parse_latex_errors(log, main.parent):
            try:
                current_xdv_mtime = xdv.stat().st_mtime_ns
                fresh_xdv = xdv_mtime_before is None or current_xdv_mtime != xdv_mtime_before
            except OSError:
                fresh_xdv = False
            if fresh_xdv:
                converter = shutil.which("xdvipdfmx")
                if converter:
                    converter_command = [converter, "-E", "-o", pdf.name, xdv.name]
                    converter_code, converter_log = run(
                        converter_command,
                        timeout=max(settings.latex_timeout, 180),
                    )
                    log += "\n\n[Loreforge XDV -> PDF stage]\n" + converter_log
                    if converter_code == 0 and pdf.exists():
                        code = 0
                        recovery_steps.append(
                            "XeLaTeX completed the document as XDV; Loreforge finished the XDV-to-PDF conversion in a separate stage."
                        )
                    else:
                        recovery_steps.append(
                            "XeLaTeX produced a complete XDV, but the XDV-to-PDF conversion failed; the converter diagnostic is shown as the blocking error."
                        )
                else:
                    log += "\n\n[Loreforge XDV -> PDF stage]\nxdvipdfmx is not installed; cannot convert the generated XDV to PDF."

        # latexmk sometimes emits only its wrapper summary. Ask the actual engine
        # for one diagnostic pass so the UI can point to the source error.
        if code != 0 and not parse_latex_errors(log, main.parent):
            binary = shutil.which(engine)
            if binary:
                direct_command = [binary, "-halt-on-error", "-interaction=nonstopmode", "-file-line-error", shell, main.name]
                direct_code, direct_log = run(direct_command)
                recovery_steps.append(f"Ran {engine} directly once to recover detailed source diagnostics from latexmk.")
                log += "\n\n[Loreforge direct-engine diagnostic pass]\n" + direct_log
                # If direct TeX succeeds, let latexmk finish references/bibliography.
                if direct_code == 0:
                    final_code, final_log = run([latexmk, mode, "-g", "-interaction=nonstopmode", "-file-line-error", shell, main.name])
                    log += "\n\n[Loreforge final latexmk pass]\n" + final_log
                    code = final_code
    else:
        binary = shutil.which(engine)
        command = [engine]
        if not binary:
            return BuildResult(False, main_rel, None, 0, command, "LaTeX engine is not installed.", [{"message": f"{engine} not installed"}], suggestions=[f"Install {engine} or use the Loreforge Docker image."], effective_engine=engine)
        command = [binary, "-interaction=nonstopmode", "-file-line-error", shell, main.name]
        code, first_log = run(command)
        second_code, second_log = run(command) if code == 0 else (code, "")
        code = second_code
        log = first_log + ("\n[Second LaTeX pass]\n" + second_log if second_log else "")

    # Keep the pipeline/controller output separate.  If a timeout or xdvipdfmx
    # failure happened, appending a huge 300-page TeX .log must not push the real
    # cause out of the FIRST BLOCKING ERROR extractor.
    pipeline_log = log

    # The engine .log often contains the actionable context even when latexmk's
    # stdout is terse. Always append its tail when it adds information.
    engine_log = main.with_suffix(".log")
    if engine_log.exists():
        try:
            detailed = engine_log.read_text(encoding="utf-8", errors="replace")[-140000:]
            if detailed and detailed not in log:
                log += "\n\n[TeX engine log]\n" + detailed
        except OSError:
            pass

    duration = time.perf_counter() - started
    pdf_out = settings.build_dir / "campaign.pdf"
    build_ok = code == 0 and pdf.exists()
    pdf_changed = False
    if pdf.exists():
        try:
            current_mtime = pdf.stat().st_mtime_ns
            pdf_changed = pdf_mtime_before is None or current_mtime != pdf_mtime_before
        except OSError:
            pdf_changed = False
    partial_pdf = bool(code != 0 and pdf.exists() and pdf_changed)
    if build_ok or partial_pdf:
        try:
            settings.build_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf, pdf_out)
        except OSError:
            build_ok = False
            partial_pdf = False
    errors = _attach_source_context(parse_latex_errors(log, main.parent), settings.project_dir)
    errors = _attach_quick_fixes(errors, settings.project_dir)
    suggestions = [] if build_ok else _latex_failure_suggestions(log, engine)
    failure_excerpt = "" if build_ok else (_extract_failure_excerpt(pipeline_log) or _extract_failure_excerpt(log))
    if partial_pdf:
        suggestions.insert(0, "XeLaTeX produced a fresh PDF despite source errors. Loreforge is showing that recoverable preview, but fix the listed source errors before treating it as the final document.")
    settings.build_dir.mkdir(parents=True, exist_ok=True)
    (settings.build_dir / "latex.log").write_text(log[-260000:], encoding="utf-8", errors="replace")
    return BuildResult(
        build_ok and pdf_out.exists(), main_rel, "/preview/pdf" if pdf_out.exists() else None,
        duration, command, log[-90000:], errors[:80], "\n".join(recovery_steps), suggestions, engine, partial_pdf, failure_excerpt,
    )

def parse_latex_errors(log: str, cwd: Path) -> list[dict]:
    """Extract concise, clickable diagnostics from latexmk/TeX output.

    ``-file-line-error`` normally produces ``file.tex:line: message`` records,
    but package/class errors and classic TeX ``! ...`` + ``l.123`` records are
    common in imported Overleaf projects. Keep both forms and deduplicate the
    cascade so the editor can focus on the first actionable failures.
    """
    errors: list[dict] = []
    seen: set[tuple] = set()

    def add(file: str | None, line: int | None, message: str) -> None:
        message = re.sub(r"\s+", " ", str(message or "")).strip()
        if not message:
            return
        normalized_file = Path(file).name if file else None
        key = (normalized_file, line, message[:240])
        if key in seen:
            return
        seen.add(key)
        errors.append({"file": normalized_file, "line": line, "message": message[:1000]})

    # latexmk/engines with -file-line-error; include project .sty/.cls because
    # custom campaign classes are often where a real failure originates.
    for m in re.finditer(r"(?m)^(.+?\.(?:tex|sty|cls|bib)):(\d+):\s*(.+)$", log, flags=re.IGNORECASE):
        path, line, message = m.groups()
        add(path, int(line), message)

    # Classic TeX form: an exclamation error followed shortly by `l.123 ...`.
    lines = log.splitlines()
    for idx, line_text in enumerate(lines):
        bang = re.match(r"^!\s+(.+)$", line_text)
        if not bang:
            continue
        source_line = None
        context = []
        for following in lines[idx + 1:idx + 7]:
            line_match = re.match(r"^l\.(\d+)\s*(.*)$", following.strip())
            if line_match:
                source_line = int(line_match.group(1))
                if line_match.group(2).strip():
                    context.append(line_match.group(2).strip())
                break
            if following.strip() and not following.startswith("?"):
                context.append(following.strip())
        message = bang.group(1).strip()
        if context:
            message += " — " + " ".join(context[:2])
        add(None, source_line, message)

    # Common wrapper-only failure: expose it only if no better diagnostic exists.
    if not errors:
        m = re.search(r"(?mi)^\s*(pdflatex|xelatex|lualatex):\s+gave an error", log)
        if m:
            add(None, None, f"{m.group(1)} reported a failure; see Build Doctor and the TeX engine log below.")
    return errors
