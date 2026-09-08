from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from .config import Settings
from .storage import get_setting, safe_project_path, set_setting


COMMENT_RE = re.compile(r"(?<!\\)%.*$")
INCLUDE_RE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")
HEADING_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection)\*?\s*\{([^{}]+)\}")
TITLE_RE = re.compile(r"\\title\s*\{([^{}]+)\}")
AUTHOR_RE = re.compile(r"\\author\s*\{([^{}]+)\}")
NEWCOMMAND_RE = re.compile(r"\\(?:newcommand|renewcommand)\s*\{?\\([A-Za-z@]+)\}?\s*(?:\[(\d+)\])?")
ENV_RE = re.compile(r"\\newenvironment\s*\{([^{}]+)\}")
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
        body_html, plain = latex_fragment_to_html(raw, settings, page_kind=current_level)
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
        html_body, plain = latex_fragment_to_html(raw, settings)
        pages = [WikiPage("setting", analysis["title"], None, "document", html_body, plain, analysis["main_file"], 1, plain[:240], 0)]

    categories: list[dict] = []
    for page in pages:
        label = page.chapter or "Setting"
        bucket = next((x for x in categories if x["title"] == label), None)
        if not bucket:
            bucket = {"title": label, "slug": slugify(label), "pages": []}
            categories.append(bucket)
        bucket["pages"].append({"slug": page.slug, "title": page.title, "excerpt": page.excerpt, "level": page.level})

    payload = {
        "title": get_setting(settings, "site_title", "") or analysis["title"],
        "tagline": get_setting(settings, "tagline", "Explore the people, places, histories, and mysteries of the campaign."),
        "author": analysis["author"],
        "generated_at": time.time(),
        "main_file": analysis["main_file"],
        "categories": categories,
        "pages": [asdict(p) for p in pages],
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


def latex_fragment_to_html(raw: str, settings: Settings, *, page_kind: str = "") -> tuple[str, str]:
    # Remove comments and document-only commands while preserving content arguments.
    raw = "\n".join(strip_comments(x) for x in raw.splitlines())
    raw = re.sub(r"\\(?:label|index|cite|pageref|ref)\s*\{[^{}]*\}", "", raw)
    raw = re.sub(r"\\(?:vspace|hspace)\*?(?:\[[^\]]*\])?\s*\{[^{}]*\}", "", raw)

    # Protect images with tokens before generic macro cleanup.  On Person of
    # Note pages, the first NPC/overlay image becomes responsive portrait art
    # rather than retaining PDF-specific TikZ page positioning.
    tokens: dict[str, str] = {}
    entity_portrait_token: str | None = None
    source_before_images = raw
    def image_sub(m: re.Match) -> str:
        nonlocal entity_portrait_token
        options = m.group(1) or ""
        ref = m.group(2)
        url = asset_url(settings, ref)
        token = f"@@LOREFORGE_IMAGE_{len(tokens)}@@"
        context = source_before_images[max(0, m.start() - 450):m.start()].lower()
        overlay_art = "\\begin{tikzpicture" in context and "\\end{tikzpicture" not in context.rsplit("\\begin{tikzpicture", 1)[-1]
        wrap_side = None
        wrap_match = re.search(r"\\begin\{wrapfigure\}\s*\{([rlio])\}", context)
        if wrap_match and "\\end{wrapfigure" not in context.rsplit("\\begin{wrapfigure", 1)[-1]:
            wrap_side = "right" if wrap_match.group(1) in {"r", "o"} else "left"
        lower_ref = ref.replace("\\", "/").lower()
        looks_like_character = any(segment in lower_ref for segment in ("/npcs/", "/characters/", "/people/", "/portraits/"))
        entity_portrait = page_kind == "entity" and entity_portrait_token is None and (looks_like_character or overlay_art)
        if entity_portrait:
            entity_portrait_token = token
        if url:
            caption = clean_inline_text(Path(ref).stem.replace("_", " "))
            classes, style = _image_classes_and_style(options, ref, entity_portrait=entity_portrait, overlay_art=overlay_art)
            if wrap_side and not entity_portrait:
                classes += f" lore-image-float-{wrap_side}"
            style_attr = f' style="{html.escape(style, quote=True)}"' if style else ""
            if Path(ref).suffix.lower() == ".pdf":
                tokens[token] = f'<figure class="{classes} lore-pdf-figure"{style_attr}><object data="{html.escape(url, quote=True)}" type="application/pdf"><a href="{html.escape(url, quote=True)}">Open {html.escape(caption)}</a></object></figure>'
            else:
                tokens[token] = f'<figure class="{classes}"{style_attr}><button class="lore-image-zoom" type="button" aria-label="Open {html.escape(caption)}"><img loading="lazy" decoding="async" src="{html.escape(url, quote=True)}" alt="{html.escape(caption)}"></button></figure>'
        else:
            tokens[token] = f'<div class="missing-asset">Missing image: {html.escape(ref)}</div>'
        return token
    raw = IMAGE_RE.sub(image_sub, raw)

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

    # Heuristic custom macros. Preserve arguments rather than dropping lore.
    analysis_macros = {x["name"]: x for x in analyze_project(settings).get("custom_macros", [])}
    for name, info in analysis_macros.items():
        if info["args"] <= 0 or info["args"] > 3:
            continue
        pattern = r"\\" + re.escape(name) + r"\s*" + "".join(r"\{([^{}]*)\}\s*" for _ in range(info["args"]))
        def custom_sub(m: re.Match, name=name, info=info) -> str:
            args = [clean_inline_text(x) for x in m.groups()]
            token = f"@@LOREFORGE_CUSTOM_{len(tokens)}@@"
            kind = info["kind"]
            if kind in {"npc-card", "location-card", "callout"}:
                title = args[0] if args else name
                body = " · ".join(args[1:])
                tokens[token] = f'<aside class="lore-callout {kind}"><div class="callout-kicker">{html.escape(name)}</div><strong>{html.escape(title)}</strong>{f"<p>{html.escape(body)}</p>" if body else ""}</aside>'
            else:
                tokens[token] = html.escape(" ".join(args))
            return token
        raw = re.sub(pattern, custom_sub, raw)

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
        if s.startswith("<figure") or s.startswith("<aside") or s.startswith("<dl class=\"lore-profile-grid") or s.startswith("<div class=\"missing-asset") or s.startswith("<div class=\"lore-table-wrap") or s.startswith("<div class=\"lore-image-caption"):
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


def compile_pdf(settings: Settings, main_file: str | None = None) -> BuildResult:
    main_rel = main_file or choose_main(settings)
    main = safe_project_path(settings, main_rel)
    if not main.exists():
        raise ValueError(f"Main file not found: {main_rel}")
    engine = settings.latex_engine
    if engine not in {"pdflatex", "xelatex", "lualatex"}:
        engine = "pdflatex"
    latexmk = shutil.which("latexmk")
    shell = "-shell-escape" if settings.allow_shell_escape else "-no-shell-escape"
    if latexmk:
        mode = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}[engine]
        cmd = [latexmk, mode, "-interaction=nonstopmode", "-file-line-error", shell, main.name]
    else:
        binary = shutil.which(engine)
        if not binary:
            return BuildResult(False, main_rel, None, 0, [engine], "LaTeX engine is not installed.", [{"message": f"{engine} not installed"}])
        cmd = [binary, "-interaction=nonstopmode", "-file-line-error", shell, main.name]
    env = os.environ.copy()
    env.setdefault("openin_any", "p")
    env.setdefault("openout_any", "p")
    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=main.parent, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=settings.latex_timeout, env=env)
        log = proc.stdout or ""
        ok = proc.returncode == 0
    except subprocess.TimeoutExpired as exc:
        log = (exc.stdout or "") + f"\nLoreforge stopped compilation after {settings.latex_timeout}s."
        ok = False
    duration = time.perf_counter() - started
    pdf = main.with_suffix(".pdf")
    pdf_out = settings.build_dir / "campaign.pdf"
    if pdf.exists():
        shutil.copy2(pdf, pdf_out)
    else:
        pdf_out.unlink(missing_ok=True)
    errors = parse_latex_errors(log, main.parent)
    (settings.build_dir / "latex.log").write_text(log[-200000:], encoding="utf-8", errors="replace")
    return BuildResult(ok and pdf_out.exists(), main_rel, "/preview/pdf" if pdf_out.exists() else None, duration, cmd, log[-50000:], errors[:80])


def parse_latex_errors(log: str, cwd: Path) -> list[dict]:
    errors: list[dict] = []
    # file.tex:123: message
    for m in re.finditer(r"(?m)^(.+?\.tex):(\d+):\s*(.+)$", log):
        path, line, message = m.groups()
        errors.append({"file": Path(path).name, "line": int(line), "message": message.strip()})
    if not errors:
        for m in re.finditer(r"(?m)^!\s+(.+)$", log):
            errors.append({"file": None, "line": None, "message": m.group(1).strip()})
    return errors
