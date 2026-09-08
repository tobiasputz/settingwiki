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
    joined = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files)
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
    dynamic_heading_macros = [m for m in analysis.get("custom_macros", []) if m.get("kind") == "heading" and int(m.get("args", 0)) >= 1]
    pages: list[WikiPage] = []
    chapter: str | None = None
    current_title: str | None = None
    current_level = "section"
    current_source = analysis["main_file"]
    current_line = 1
    buffer: list[str] = []
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
        body_html, plain = latex_fragment_to_html(raw, settings)
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
            flush()
            if match:
                level, title = match.group(1), clean_inline_text(match.group(2))
                remainder = HEADING_RE.sub("", line).strip()
            else:
                macro_name = dynamic_info["name"].lower()
                level = "chapter" if ("chapter" in macro_name or "part" in macro_name) else ("subsection" if "subsection" in macro_name else "section")
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
    ref = ref.strip().replace("\\", "/")
    candidates = [project_root / ref]
    if not Path(ref).suffix:
        candidates.extend(project_root / f"{ref}{ext}" for ext in (".png", ".jpg", ".jpeg", ".webp", ".pdf", ".svg"))
    for p in candidates:
        try:
            r = p.resolve()
            if (r == project_root.resolve() or project_root.resolve() in r.parents) and r.exists() and r.is_file():
                return r
        except OSError:
            pass
    # Search by basename as a compatibility fallback for Overleaf projects.
    target = Path(ref).name
    for p in project_root.rglob(target):
        if p.is_file():
            return p
    return None


def asset_url(settings: Settings, ref: str) -> str | None:
    path = _find_asset(settings.project_dir, ref)
    if not path:
        return None
    rel = path.relative_to(settings.project_dir).as_posix()
    return "/project-asset/" + quote(rel)


def latex_fragment_to_html(raw: str, settings: Settings) -> tuple[str, str]:
    # Remove comments and document-only commands while preserving content arguments.
    raw = "\n".join(strip_comments(x) for x in raw.splitlines())
    raw = re.sub(r"\\(?:label|index|cite|pageref|ref)\s*\{[^{}]*\}", "", raw)
    raw = re.sub(r"\\(?:vspace|hspace)\*?(?:\[[^\]]*\])?\s*\{[^{}]*\}", "", raw)

    # Protect images with tokens before generic macro cleanup.
    tokens: dict[str, str] = {}
    def image_sub(m: re.Match) -> str:
        ref = m.group(2)
        url = asset_url(settings, ref)
        token = f"@@LOREFORGE_IMAGE_{len(tokens)}@@"
        if url:
            caption = clean_inline_text(Path(ref).stem.replace("_", " "))
            if Path(ref).suffix.lower() == ".pdf":
                tokens[token] = f'<figure class="lore-image lore-pdf-figure"><object data="{html.escape(url, quote=True)}" type="application/pdf"><a href="{html.escape(url, quote=True)}">Open {html.escape(caption)}</a></object></figure>'
            else:
                tokens[token] = f'<figure class="lore-image"><img loading="lazy" src="{html.escape(url, quote=True)}" alt="{html.escape(caption)}"></figure>'
        else:
            tokens[token] = f'<div class="missing-asset">Missing image: {html.escape(ref)}</div>'
        return token
    raw = IMAGE_RE.sub(image_sub, raw)

    # Convert simple environments to markdown-ish sentinels.
    raw = re.sub(r"\\begin\{(?:itemize|description)\}", "\n@@UL_START@@\n", raw)
    raw = re.sub(r"\\end\{(?:itemize|description)\}", "\n@@UL_END@@\n", raw)
    raw = re.sub(r"\\begin\{enumerate\}", "\n@@OL_START@@\n", raw)
    raw = re.sub(r"\\end\{enumerate\}", "\n@@OL_END@@\n", raw)
    raw = re.sub(r"\\begin\{(?:quote|quotation)\}", "\n@@QUOTE_START@@\n", raw)
    raw = re.sub(r"\\end\{(?:quote|quotation)\}", "\n@@QUOTE_END@@\n", raw)
    raw = re.sub(r"\\item(?:\[[^\]]*\])?", "\n@@ITEM@@ ", raw)

    # Sub-headings within a page.
    raw = re.sub(r"\\subsection\*?\s*\{([^{}]+)\}", lambda m: f"\n@@H2@@{clean_inline_text(m.group(1))}\n", raw)
    raw = re.sub(r"\\subsubsection\*?\s*\{([^{}]+)\}", lambda m: f"\n@@H3@@{clean_inline_text(m.group(1))}\n", raw)
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
    raw = raw.replace("\\\\", "\n")
    raw = raw.replace("{", "").replace("}", "")

    # Escape remaining prose while preserving tokens/sentinels.
    escaped = html.escape(raw)
    for token, value in tokens.items():
        escaped = escaped.replace(html.escape(token), value)
    for sentinel in ("UL_START", "UL_END", "OL_START", "OL_END", "QUOTE_START", "QUOTE_END", "ITEM", "H2", "H3", "H4"):
        escaped = escaped.replace(html.escape(f"@@{sentinel}@@"), f"@@{sentinel}@@")

    # Block formatter.
    lines = [x.rstrip() for x in escaped.splitlines()]
    out: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    quote_open = False

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
        if s.startswith("<figure") or s.startswith("<aside") or s.startswith("<div class=\"missing-asset"):
            flush_p(); out.append(s); continue
        paragraph.append(s)
    flush_p()
    if list_kind: out.append(f"</{list_kind}>")
    if quote_open: out.append("</blockquote>")
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
