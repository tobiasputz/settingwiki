from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

from .config import Settings
from .storage import get_setting, set_setting

NON_MONSTER_KINDS = {"item", "feat", "action", "homebrew"}
HOME_BREW_SECTIONS = {
    "ancestry": "Ancestries",
    "archetype": "Archetypes",
    "class": "Class Feats",
    "general": "General & Skill Feats",
    "actions": "Actions & Activities",
    "items": "Items & Equipment",
    "other": "Other Homebrew",
}
HOME_BREW_SOURCE_TITLES = {
    "ancestry": "Ancestries",
    "archetype": "Archetypes",
    "class": "Classes",
    "general": "General Homebrew",
    "actions": "Actions & Activities",
    "items": "Items & Equipment",
    "other": "Other Homebrew",
}
FILE_HOME_BREW_SETTING = "homebrew_file_kinds_v2"


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _norm_path(path: str | None) -> str:
    return str(path or "").replace("\\", "/").strip("/")


def load_homebrew_file_kinds(settings: Settings) -> dict[str, str]:
    try:
        raw = json.loads(get_setting(settings, FILE_HOME_BREW_SETTING, "{}") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for path, kind in raw.items():
        path = _norm_path(path)
        kind = str(kind or "codex").strip().lower()
        if path and kind in HOME_BREW_SECTIONS:
            out[path] = kind
    return out


def save_homebrew_file_kinds(settings: Settings, mapping: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for path, kind in (mapping or {}).items():
        path = _norm_path(path)
        kind = str(kind or "codex").strip().lower()
        if path and kind in HOME_BREW_SECTIONS:
            cleaned[path] = kind
    set_setting(settings, FILE_HOME_BREW_SETTING, json.dumps(cleaned, sort_keys=True, separators=(",", ":")))
    return cleaned


def file_homebrew_kind(settings: Settings, path: str | None) -> str:
    return load_homebrew_file_kinds(settings).get(_norm_path(path), "codex")


def set_file_homebrew_kind(settings: Settings, path: str, kind: str) -> dict[str, str]:
    path = _norm_path(path)
    kind = str(kind or "codex").strip().lower()
    if kind != "codex" and kind not in HOME_BREW_SECTIONS:
        raise ValueError("Unknown Homebrew library placement.")
    mapping = load_homebrew_file_kinds(settings)
    if kind == "codex":
        mapping.pop(path, None)
    else:
        mapping[path] = kind
    return save_homebrew_file_kinds(settings, mapping)


def move_file_homebrew_metadata(settings: Settings, old_path: str, new_path: str, *, is_dir: bool = False) -> None:
    old_path, new_path = _norm_path(old_path), _norm_path(new_path)
    mapping = load_homebrew_file_kinds(settings)
    changed = False
    updated: dict[str, str] = {}
    for path, kind in mapping.items():
        if path == old_path or (is_dir and path.startswith(old_path.rstrip("/") + "/")):
            suffix = path[len(old_path):].lstrip("/")
            target = new_path.rstrip("/") + ("/" + suffix if suffix else "")
            updated[target] = kind
            changed = True
        else:
            updated[path] = kind
    if changed:
        save_homebrew_file_kinds(settings, updated)


def delete_file_homebrew_metadata(settings: Settings, path: str, *, is_dir: bool = False) -> None:
    path = _norm_path(path)
    mapping = load_homebrew_file_kinds(settings)
    updated = {p: k for p, k in mapping.items() if not (p == path or (is_dir and p.startswith(path.rstrip("/") + "/")))}
    if updated != mapping:
        save_homebrew_file_kinds(settings, updated)


def is_homebrew_source_path(path: str | None) -> bool:
    parts = [p.casefold() for p in PurePosixPath(_norm_path(path)).parts]
    return bool(parts and parts[0] in {"homebrew", "home-brew", "custom"})


def source_homebrew_bucket(path: str | None) -> tuple[str, str]:
    parts = list(PurePosixPath(_norm_path(path)).parts)
    if not parts or not is_homebrew_source_path(path):
        return "other", "Source files"
    lower = [p.casefold() for p in parts]
    section = "other"
    if len(lower) > 1:
        if lower[1] in {"ancestry", "ancestries"}: section = "ancestry"
        elif lower[1] in {"archetype", "archetypes"}: section = "archetype"
        elif lower[1] in {"class", "classes"}: section = "class"
        elif lower[1] in {"action", "actions", "activities"}: section = "actions"
        elif lower[1] in {"item", "items", "equipment"}: section = "items"
    group = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else "Source files")
    return section, group.replace("-", " ").replace("_", " ").strip().title() or "Source files"


def page_homebrew_kind(page: dict | None) -> str:
    page = page or {}
    kind = str(page.get("homebrew_kind") or (page.get("presentation") or {}).get("homebrew_kind") or "codex").strip().lower()
    if kind != "codex":
        return kind if kind in HOME_BREW_SECTIONS else "other"
    if is_homebrew_source_path(page.get("source_file")):
        section, _ = source_homebrew_bucket(page.get("source_file"))
        return section
    return "codex"


def is_homebrew_page(page: dict | None) -> bool:
    return page_homebrew_kind(page) != "codex"


def _traits(payload: dict) -> list[str]:
    return [x.strip() for x in str(payload.get("traits") or "").split(",") if x.strip()]


def classify_homebrew(row: dict) -> dict:
    payload = dict(row.get("payload") or {})
    kind = str(row.get("kind") or "homebrew").strip().lower()
    document = str(payload.get("homebrew_document") or "").strip().lower()
    explicit = str(payload.get("library_section") or "auto").strip().lower()
    group = str(payload.get("library_group") or "").strip()
    traits = _traits(payload)
    traits_low = {t.casefold() for t in traits}

    if kind == "homebrew" and document in {"feat", "action", "equipment", "item", "weapon", "armor", "consumable", "ancestry", "archetype"}:
        if document == "action":
            effective = "action"
        elif document == "feat":
            effective = "feat"
        elif document in {"ancestry", "archetype"}:
            effective = document
        else:
            effective = "item"
    else:
        effective = kind

    if explicit in HOME_BREW_SECTIONS:
        section = explicit
    elif effective in {"ancestry", "archetype"}:
        section = effective
    elif effective == "action":
        section = "actions"
    elif effective == "item":
        section = "items"
    elif effective == "feat":
        category = str(payload.get("feat_category") or "").strip().lower()
        if category == "ancestry" or "ancestry" in traits_low:
            section = "ancestry"
        elif category == "archetype" or "archetype" in traits_low:
            section = "archetype"
        elif category == "class" or "class" in traits_low:
            section = "class"
        else:
            section = "general"
    else:
        section = "other"

    if not group:
        if effective == "ancestry": group = str(row.get("title") or payload.get("ancestry_trait") or "").strip()
        elif effective == "archetype": group = str(row.get("title") or payload.get("archetype_name") or "").strip()
        elif section == "ancestry": group = str(payload.get("ancestry_trait") or "").strip()
        elif section == "archetype": group = str(payload.get("archetype_name") or "").strip()
        elif section == "class": group = str(payload.get("class_name") or "").strip()
        elif section == "items": group = str(payload.get("item_type") or "Equipment").strip().replace("_", " ").title()
        elif section == "actions": group = "Actions & Activities"
        elif section == "general": group = str(payload.get("feat_category") or "General").strip().title()
    if not group:
        generic = {"common","uncommon","rare","unique","feat","skill","general","ancestry","archetype","class","downtime","exploration","concentrate","manipulate","fortune","incapacitation"}
        group = next((t for t in traits if t.casefold() not in generic), "Ungrouped")

    level_raw = payload.get("level", 0)
    try: level = int(level_raw)
    except (TypeError, ValueError): level = 0
    return {
        "section": section,
        "section_title": HOME_BREW_SECTIONS.get(section, "Other Homebrew"),
        "group": group or "Ungrouped",
        "level": level,
        "effective_kind": effective,
        "published": truthy(payload.get("homebrew_publish")),
    }


def group_homebrew(rows: list[dict], *, include_drafts: bool = False) -> list[dict]:
    grouped: dict[str, dict[str, list[dict]]] = {}
    for source in rows:
        if str(source.get("kind") or "").lower() not in NON_MONSTER_KINDS:
            continue
        if str(source.get("kind") or "").lower()=="homebrew" and str((source.get("payload") or {}).get("homebrew_document") or "").lower() in {"npc","monster","creature"}:
            continue
        row = dict(source)
        meta = classify_homebrew(row)
        if not include_drafts and not meta["published"]:
            continue
        row["library"] = meta
        grouped.setdefault(meta["section"], {}).setdefault(meta["group"], []).append(row)
    order = ["ancestry", "archetype", "class", "general", "actions", "items", "other"]
    result=[]
    for section in order:
        groups=grouped.get(section, {})
        if not groups: continue
        rendered=[]
        for name, entries in sorted(groups.items(), key=lambda kv: kv[0].casefold()):
            entries.sort(key=lambda x: (int(x["library"].get("level") or 0), str(x.get("title") or "").casefold()))
            rendered.append({"name":name,"entries":entries})
        result.append({"key":section,"title":HOME_BREW_SECTIONS[section],"groups":rendered})
    return result


def latex_escape(value: Any) -> str:
    text=str(value or "")
    replacements={"\\":r"\textbackslash{}","&":r"\&","%":r"\%","$":r"\$","#":r"\#","_":r"\_","{":r"\{","}":r"\}","~":r"\textasciitilde{}","^":r"\textasciicircum{}"}
    return "".join(replacements.get(ch,ch) for ch in text)


def _rules_body(row: dict) -> str:
    payload=dict(row.get("payload") or {})
    lines=[]
    for label,key in (("Access","access"),("Prerequisites","prerequisites"),("Trigger","trigger"),("Requirements","requirements"),("Frequency","frequency"),("Special","special")):
        value=str(payload.get(key) or "").strip()
        if value: lines.append(r"\textbf{"+label+":} "+latex_escape(value)+r"\\")
    desc=str(payload.get("description") or "").strip() or str(row.get("summary") or "").strip()
    if desc: lines.append(latex_escape(desc).replace("\n", "\n\n"))
    return "\n".join(lines).strip()


def _bundle_rule_latex(rule: dict, *, default_category: str = "general") -> str:
    kind=str(rule.get("kind") or "feat").strip().lower()
    title=latex_escape(rule.get("title") or "Untitled")
    level=int(rule.get("level") or 0)
    traits_raw=rule.get("traits") or ""
    if isinstance(traits_raw, list): traits=", ".join(str(x).strip() for x in traits_raw if str(x).strip())
    else: traits=str(traits_raw)
    traits=latex_escape(traits)
    lines=[]
    for label,key in (("Access","access"),("Prerequisites","prerequisites"),("Frequency","frequency"),("Trigger","trigger"),("Requirements","requirements"),("Special","special")):
        value=str(rule.get(key) or "").strip()
        if value: lines.append(r"\textbf{"+label+":} "+latex_escape(value)+r"\\")
    desc=str(rule.get("description") or "").strip()
    if desc: lines.append(latex_escape(desc).replace("\n", "\n\n"))
    body="\n".join(lines).strip()
    action=str(rule.get("action_cost") or "").strip().lower()
    if kind=="action":
        glyph={"1":r"\actionOne","2":r"\actionTwo","3":r"\actionThree","reaction":r"\reaction","free":r"\freeAction"}.get(action,"")
        return f"\\action{{{title}}}{{{glyph}}}{{{traits}}}{{%\n{body}\n}}\n"
    return f"\\feat{{{title}}}{{{level}}}{{{traits}}}{{%\n{body}\n}}\n"


def _bundle_latex_snippet(row: dict, document: str) -> str:
    payload=dict(row.get("payload") or {})
    title=latex_escape(row.get("title") or ("Custom Ancestry" if document=="ancestry" else "Custom Archetype"))
    description=str(payload.get("description") or row.get("summary") or "").strip()
    out=[f"\\section{{{title}}}"]
    if description: out.extend([latex_escape(description).replace("\n", "\n\n"), ""])
    if document=="ancestry":
        out.append(r"\subsection{Ancestry Statistics}")
        stats=[]
        for label,key,suffix in (("Hit Points","ancestry_hp",""),("Size","ancestry_size",""),("Speed","ancestry_speed"," feet"),("Reach","ancestry_reach"," feet"),("Vision","ancestry_vision",""),("Languages","ancestry_languages",""),("Additional Languages","ancestry_additional_languages",""),("Traits","ancestry_traits",""),("Ability Boosts","ancestry_boosts",""),("Free Ability Boosts","ancestry_free_boosts",""),("Ability Flaws","ancestry_flaws","")):
            value=str(payload.get(key) or "").strip()
            if value: stats.append(r"\textbf{"+label+":} "+latex_escape(value)+latex_escape(suffix)+r"\\")
        out.extend(stats or [r"\emph{Ancestry statistics not yet specified.}"])
        heritages=payload.get("heritages") if isinstance(payload.get("heritages"),list) else []
        if heritages:
            out.extend(["",r"\subsection{Heritages}"])
            for h in heritages:
                name=latex_escape(h.get("title") or h.get("name") or "Unnamed Heritage")
                out.append(f"\\subsubsection{{{name}}}")
                traits=h.get("traits") or ""
                if traits: out.append(r"\textbf{Traits:} "+latex_escape(traits)+r"\\")
                text=str(h.get("description") or "").strip()
                if text: out.append(latex_escape(text).replace("\n","\n\n"))
        rules=payload.get("bundle_feats") if isinstance(payload.get("bundle_feats"),list) else []
        if rules:
            out.extend(["",r"\subsection{Ancestry Feats}"])
            current=None
            for rule in sorted(rules,key=lambda x:(int(x.get("level") or 0),str(x.get("title") or "").casefold())):
                level=int(rule.get("level") or 0)
                if level!=current:
                    current=level; out.append(f"\\subsubsection{{Level {level}}}")
                out.append(_bundle_rule_latex(rule,default_category="ancestry").rstrip())
    else:
        archetype_traits=str(payload.get("archetype_traits") or "").strip()
        access=str(payload.get("archetype_access") or "").strip()
        if archetype_traits: out.extend([r"\textbf{Traits:} "+latex_escape(archetype_traits)+r"\\",""])
        if access: out.extend([r"\textbf{Access:} "+latex_escape(access)+r"\\",""])
        dedication={
            "kind":"feat","title":str(payload.get("dedication_title") or f"{row.get('title') or 'Archetype'} Dedication"),
            "level":int(payload.get("dedication_level") or 2),"traits":str(payload.get("dedication_traits") or "archetype, dedication"),
            "action_cost":str(payload.get("dedication_action_cost") or ""),"prerequisites":str(payload.get("dedication_prerequisites") or ""),
            "frequency":str(payload.get("dedication_frequency") or ""),"trigger":str(payload.get("dedication_trigger") or ""),
            "requirements":str(payload.get("dedication_requirements") or ""),"special":str(payload.get("dedication_special") or ""),
            "description":str(payload.get("dedication_description") or ""),
        }
        if str(dedication.get("title") or "").strip():
            out.extend(["",r"\subsection{Dedication}",_bundle_rule_latex(dedication,default_category="archetype").rstrip()])
        rules=payload.get("bundle_feats") if isinstance(payload.get("bundle_feats"),list) else []
        if rules:
            out.extend(["",r"\subsection{Archetype Feats}"])
            current=None
            for rule in sorted(rules,key=lambda x:(int(x.get("level") or 0),str(x.get("title") or "").casefold())):
                level=int(rule.get("level") or 0)
                if level!=current:
                    current=level; out.append(f"\\subsubsection{{Level {level}}}")
                out.append(_bundle_rule_latex(rule,default_category="archetype").rstrip())
    return "\n\n".join(x for x in out if x is not None).strip()+"\n"


def homebrew_latex_snippet(row: dict) -> str:
    payload=dict(row.get("payload") or {})
    document=str(payload.get("homebrew_document") or "").strip().lower()
    if document in {"ancestry", "archetype"}:
        return _bundle_latex_snippet(row, document)
    meta=classify_homebrew(row)
    kind=meta["effective_kind"]
    title=latex_escape(row.get("title") or "Untitled")
    traits=latex_escape(", ".join(_traits(payload)))
    body=_rules_body(row)
    level=meta["level"]
    if kind == "feat":
        return f"\\feat{{{title}}}{{{level}}}{{{traits}}}{{%\n{body}\n}}\n"
    if kind == "action":
        raw=str(payload.get("action_cost") or payload.get("homebrew_actions") or "").strip().lower()
        glyph={"1":r"\actionOne","2":r"\actionTwo","3":r"\actionThree","reaction":r"\reaction","free":r"\freeAction"}.get(raw, "")
        return f"\\action{{{title}}}{{{glyph}}}{{{traits}}}{{%\n{body}\n}}\n"
    if kind == "item":
        return f"\\itemtemplate{{{title}}}{{Item {level}}}{{{traits}}}{{%\n{body}\n}}\n"
    document=str(payload.get("homebrew_document") or "homebrew").lower()
    if document == "feat":
        return f"\\feat{{{title}}}{{{level}}}{{{traits}}}{{%\n{body}\n}}\n"
    if document == "action":
        raw=str(payload.get("homebrew_actions") or "").strip().lower();glyph={"1":r"\actionOne","2":r"\actionTwo","3":r"\actionThree","reaction":r"\reaction","free":r"\freeAction"}.get(raw, "")
        return f"\\action{{{title}}}{{{glyph}}}{{{traits}}}{{%\n{body}\n}}\n"
    return f"% {title}\n{body}\n"


def homebrew_marker(entry_id: int) -> tuple[str, str]:
    return f"% SEEKER-HOMEBREW:{int(entry_id)}:BEGIN", f"% SEEKER-HOMEBREW:{int(entry_id)}:END"


def remove_latex_block(existing: str, entry_id: int) -> tuple[str, bool]:
    start, end = homebrew_marker(entry_id)
    pattern = re.compile(r"(?:\n{0,2})?" + re.escape(start) + r".*?" + re.escape(end) + r"(?:\n{0,2})?", re.S)
    updated, count = pattern.subn("\n", existing)
    return updated.strip("\n") + ("\n" if updated.strip("\n") else ""), bool(count)


def _marked_block(entry_id: int, snippet: str) -> str:
    start, end = homebrew_marker(entry_id)
    return f"{start}\n{snippet.rstrip()}\n{end}"


def upsert_latex_block(existing: str, entry_id: int, snippet: str) -> str:
    start, end = homebrew_marker(entry_id)
    block=_marked_block(entry_id,snippet)
    pattern=re.compile(re.escape(start)+r".*?"+re.escape(end), re.S)
    if pattern.search(existing):
        return pattern.sub(lambda _m:block, existing)
    prefix=existing.rstrip()
    return (prefix+"\n\n" if prefix else "")+block+"\n"


def insert_latex_block_in_heading(existing: str, entry_id: int, snippet: str, *, heading_level: str = "", heading_title: str = "", heading_index: int = 0) -> str:
    """Insert a stable Seeker block at the end of a chosen LaTeX heading scope.

    Re-exporting the same entry updates the marker block rather than adding a
    second command.  When no heading is selected the block is appended normally.
    """
    cleaned, _ = remove_latex_block(existing, entry_id)
    level = str(heading_level or "").strip().lower()
    title = str(heading_title or "").strip()
    if not level or not title:
        return upsert_latex_block(cleaned, entry_id, snippet)
    order = {"part": 0, "chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4}
    if level not in order:
        return upsert_latex_block(cleaned, entry_id, snippet)
    heading_re = re.compile(r"\\(part|chapter|section|subsection|subsubsection)\*?\s*\{([^{}]+)\}")
    matches = list(heading_re.finditer(cleaned))
    candidates = [m for m in matches if m.group(1)==level and re.sub(r"\s+", " ", m.group(2)).strip()==title]
    if not candidates:
        return upsert_latex_block(cleaned, entry_id, snippet)
    idx = max(0, min(int(heading_index or 0), len(candidates)-1))
    selected = candidates[idx]
    insert_at = len(cleaned)
    selected_rank = order[level]
    for m in matches:
        if m.start() <= selected.start():
            continue
        if order.get(m.group(1), 99) <= selected_rank:
            insert_at = m.start()
            break
    block = "\n\n" + _marked_block(entry_id, snippet) + "\n\n"
    return cleaned[:insert_at].rstrip() + block + cleaned[insert_at:].lstrip("\n")

# --- 7.4.3 source-linked Forge synchronization ---------------------------------
# Existing classified LaTeX ancestry/archetype files can be opened in the Forge.
# The LaTeX file remains authoritative: Forge changes are written back in place,
# while new feats are inserted into their matching level scope.

_SOURCE_HEADING_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection)\*?\s*\{([^{}]+)\}", re.I)
_SOURCE_HEADING_RANK = {"part": 0, "chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4}


def _source_key(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\\([%&#_$])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _read_braced_span(text: str, pos: int) -> tuple[str, int] | None:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text) or text[pos] != "{":
        return None
    depth = 0
    start = pos + 1
    i = pos
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return None


def _balanced_command_spans(text: str, name: str, nargs: int) -> list[dict]:
    out: list[dict] = []
    pattern = re.compile(r"\\" + re.escape(name) + r"\b")
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if not match:
            break
        pos = match.end()
        args: list[str] = []
        ok = True
        for _ in range(nargs):
            parsed = _read_braced_span(text, pos)
            if not parsed:
                ok = False
                break
            value, pos = parsed
            args.append(value)
        if ok:
            out.append({"start": match.start(), "end": pos, "args": args})
            cursor = pos
        else:
            cursor = match.end()
    return out


def _heading_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    for match in _SOURCE_HEADING_RE.finditer(text):
        level = match.group(1).lower()
        rows.append({
            "level": level,
            "rank": _SOURCE_HEADING_RANK[level],
            "title": match.group(2),
            "start": match.start(),
            "end": match.end(),
        })
    return rows


def _heading_scope_end(text: str, headings: list[dict], heading: dict) -> int:
    for row in headings:
        if row["start"] <= heading["start"]:
            continue
        if row["rank"] <= heading["rank"]:
            return int(row["start"])
    return len(text)


def _level_from_heading(title: str) -> int | None:
    value = _source_key(title)
    match = re.search(r"\blevel\s*(\d+)\b", value)
    if not match:
        match = re.search(r"\b(\d+)(?:st|nd|rd|th)?\s+level\b", value)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _ordinal(value: int) -> str:
    n = int(value)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _level_heading_title(example: str, level: int) -> str:
    raw = str(example or "").strip()
    if re.search(r"\blevel\s*\d+\b", raw, re.I):
        return re.sub(r"(\blevel\s*)\d+", rf"\g<1>{int(level)}", raw, count=1, flags=re.I)
    if re.search(r"\b\d+(?:st|nd|rd|th)?\s+level\b", raw, re.I):
        return re.sub(r"\b\d+(?:st|nd|rd|th)?(?=\s+level\b)", _ordinal(level), raw, count=1, flags=re.I)
    return f"{_ordinal(level)} Level"


def _rule_compare(rule: dict) -> dict:
    keep = ("kind", "title", "level", "traits", "action_cost", "access", "prerequisites", "frequency", "trigger", "requirements", "special", "description")
    out = {key: rule.get(key, "") for key in keep}
    traits = out.get("traits")
    if isinstance(traits, list):
        out["traits"] = ", ".join(str(x).strip() for x in traits if str(x).strip())
    try:
        out["level"] = int(out.get("level") or 0)
    except (TypeError, ValueError):
        out["level"] = 0
    return out


def _heritage_compare(row: dict) -> dict:
    return {
        "title": str(row.get("title") or row.get("name") or "").strip(),
        "traits": str(row.get("traits") or "").strip(),
        "rarity": str(row.get("rarity") or "common").strip(),
        "description": str(row.get("description") or "").strip(),
    }


def _find_command_by_title(text: str, name: str, title: str, nargs: int = 4) -> dict | None:
    wanted = _source_key(title)
    if not wanted:
        return None
    for row in _balanced_command_spans(text, name, nargs):
        if _source_key(row["args"][0]) == wanted:
            return row
    return None


def _find_level_heading_for_rule(text: str, command_start: int) -> tuple[dict | None, int | None]:
    headings = _heading_rows(text)
    active: dict | None = None
    for row in headings:
        if row["start"] >= command_start:
            break
        if _level_from_heading(row["title"]) is not None:
            active = row
    return active, (_level_from_heading(active["title"]) if active else None)


def _feat_heading_candidates(text: str) -> list[dict]:
    headings = _heading_rows(text)
    commands = _balanced_command_spans(text, "feat", 4)
    rows: list[dict] = []
    parent = _feat_parent_heading(text)
    parent_end = _heading_scope_end(text, headings, parent) if parent else None
    parent_rank = int(parent["rank"]) if parent else None
    for heading in headings:
        level = _level_from_heading(heading["title"])
        if level is None:
            continue
        # A level heading inside an explicit Feats section is meaningful even
        # while empty. This matters when a GM adds the first feat at a level
        # already present in the source: reuse that heading instead of creating
        # a duplicate "17th Level" block.
        if parent and parent["end"] <= heading["start"] < int(parent_end) and int(heading["rank"]) > int(parent_rank):
            rows.append({**heading, "feat_level": level})
            continue
        end = _heading_scope_end(text, headings, heading)
        if any(heading["end"] <= command["start"] < end for command in commands):
            rows.append({**heading, "feat_level": level})
    return rows


def _feat_parent_heading(text: str) -> dict | None:
    headings = _heading_rows(text)
    candidates = [row for row in headings if "feat" in _source_key(row["title"])]
    if not candidates:
        return None
    # Prefer a heading that actually owns one or more \feat commands.
    commands = _balanced_command_spans(text, "feat", 4)
    for heading in reversed(candidates):
        end = _heading_scope_end(text, headings, heading)
        if any(heading["end"] <= command["start"] < end for command in commands):
            return heading
    return candidates[-1]


def _insert_rule_at_level(text: str, rule: dict) -> tuple[str, str]:
    try:
        level = int(rule.get("level") or 0)
    except (TypeError, ValueError):
        level = 0
    snippet = _bundle_rule_latex(rule).rstrip()
    headings = _heading_rows(text)
    level_rows = _feat_heading_candidates(text)
    exact = next((row for row in level_rows if int(row.get("feat_level") or -999) == level), None)
    if exact:
        insert_at = _heading_scope_end(text, headings, exact)
        before = text[:insert_at].rstrip()
        after = text[insert_at:].lstrip("\n")
        return before + "\n\n" + snippet + "\n\n" + after, f"level-{level}"

    # Infer the author's level-heading style/rank from the existing feat levels.
    if level_rows:
        level_rows = sorted(level_rows, key=lambda row: row["start"])
        sample = level_rows[0]
        heading_level = sample["level"]
        heading_title = _level_heading_title(sample["title"], level)
        higher = next((row for row in sorted(level_rows, key=lambda row: int(row["feat_level"])) if int(row["feat_level"]) > level), None)
        if higher:
            insert_at = higher["start"]
        else:
            parent = _feat_parent_heading(text)
            insert_at = _heading_scope_end(text, headings, parent) if parent else _heading_scope_end(text, headings, level_rows[-1])
        block = f"\\{heading_level}{{{heading_title}}}\n{snippet}"
        return text[:insert_at].rstrip() + "\n\n" + block + "\n\n" + text[insert_at:].lstrip("\n"), f"new-level-{level}"

    parent = _feat_parent_heading(text)
    if parent:
        child_rank = min(4, int(parent["rank"]) + 1)
        child_level = next((name for name, rank in _SOURCE_HEADING_RANK.items() if rank == child_rank), "subsection")
        insert_at = _heading_scope_end(text, headings, parent)
        block = f"\\{child_level}{{{_ordinal(level)} Level}}\n{snippet}"
        return text[:insert_at].rstrip() + "\n\n" + block + "\n\n" + text[insert_at:].lstrip("\n"), f"new-level-{level}"

    # Last-resort conventional section. This path is intentionally conservative:
    # it only runs for a source with no recognizable feat structure at all.
    end_doc = re.search(r"\\end\{document\}", text, re.I)
    insert_at = end_doc.start() if end_doc else len(text)
    block = f"\\section{{Ancestry Feats}}\n\\subsection{{{_ordinal(level)} Level}}\n{snippet}"
    return text[:insert_at].rstrip() + "\n\n" + block + "\n\n" + text[insert_at:].lstrip("\n"), f"new-feat-section-{level}"


def _replace_or_move_rule(text: str, rule: dict, snapshot: dict | None) -> tuple[str, list[str]]:
    changes: list[str] = []
    original_title = str(rule.get("_source_original_title") or (snapshot or {}).get("title") or "").strip()
    found = _find_command_by_title(text, "feat", original_title or str(rule.get("title") or ""), 4)
    if not found:
        updated, where = _insert_rule_at_level(text, rule)
        return updated, [f"added {rule.get('title') or 'feat'} to {where}"]
    _heading, current_level = _find_level_heading_for_rule(text, int(found["start"]))
    try:
        new_level = int(rule.get("level") or 0)
    except (TypeError, ValueError):
        new_level = 0
    command = _bundle_rule_latex(rule).rstrip()
    if current_level is not None and current_level != new_level:
        stripped = text[:found["start"]].rstrip() + "\n" + text[found["end"]:].lstrip("\n")
        updated, where = _insert_rule_at_level(stripped, rule)
        return updated, [f"moved {rule.get('title') or original_title} to {where}"]
    updated = text[:found["start"]] + command + text[found["end"]:]
    changes.append(f"updated {rule.get('title') or original_title}")
    return updated, changes


def _remove_source_feat(text: str, title: str) -> tuple[str, bool]:
    found = _find_command_by_title(text, "feat", title, 4)
    if not found:
        return text, False
    updated = text[:found["start"]].rstrip() + "\n" + text[found["end"]:].lstrip("\n")
    return updated, True


def _find_heritage_parent(text: str) -> dict | None:
    headings = _heading_rows(text)
    for row in headings:
        title = _source_key(row["title"])
        if "heritage" in title and ("heritages" in title or title.endswith("heritage")):
            return row
    return None


def _find_heritage_block(text: str, title: str) -> tuple[dict, int] | None:
    parent = _find_heritage_parent(text)
    if not parent:
        return None
    headings = _heading_rows(text)
    parent_end = _heading_scope_end(text, headings, parent)
    child_rank = int(parent["rank"]) + 1
    wanted = _source_key(title)
    for row in headings:
        if not (parent["end"] <= row["start"] < parent_end):
            continue
        if row["rank"] != child_rank or _source_key(row["title"]) != wanted:
            continue
        return row, _heading_scope_end(text, headings, row)
    return None


def _heritage_block_text(level: str, heritage: dict) -> str:
    title = latex_escape(heritage.get("title") or heritage.get("name") or "Unnamed Heritage")
    traits = str(heritage.get("traits") or "").strip()
    desc = str(heritage.get("description") or "").strip()
    rows = [f"\\{level}{{{title}}}"]
    if traits:
        rows.append(r"\textbf{Traits:} " + latex_escape(traits) + r"\\")
    if desc:
        rows.append(latex_escape(desc).replace("\n", "\n\n"))
    return "\n".join(rows)


def _sync_heritages(text: str, current: list[dict], previous: list[dict]) -> tuple[str, list[str]]:
    changes: list[str] = []
    current_origins = {_source_key(str(row.get("_source_original_title") or "")) for row in current if row.get("_source_original_title")}
    for old in previous:
        original = str(old.get("_source_original_title") or old.get("title") or old.get("name") or "").strip()
        if original and _source_key(original) not in current_origins:
            block = _find_heritage_block(text, original)
            if block:
                row, end = block
                text = text[:row["start"]].rstrip() + "\n\n" + text[end:].lstrip("\n")
                changes.append(f"removed heritage {original}")
    previous_by_origin = {_source_key(str(row.get("_source_original_title") or row.get("title") or row.get("name") or "")): row for row in previous}
    for heritage in current:
        original = str(heritage.get("_source_original_title") or "").strip()
        old = previous_by_origin.get(_source_key(original)) if original else None
        if old and _heritage_compare(old) == _heritage_compare(heritage):
            continue
        if original:
            block = _find_heritage_block(text, original)
            if block:
                row, end = block
                replacement = _heritage_block_text(row["level"], heritage)
                text = text[:row["start"]] + replacement + text[end:]
                changes.append(f"updated heritage {heritage.get('title') or original}")
                continue
        parent = _find_heritage_parent(text)
        if parent:
            headings = _heading_rows(text)
            rank = min(4, int(parent["rank"]) + 1)
            level = next((name for name, value in _SOURCE_HEADING_RANK.items() if value == rank), "subsection")
            insert_at = _heading_scope_end(text, headings, parent)
            block_text = _heritage_block_text(level, heritage)
            text = text[:insert_at].rstrip() + "\n\n" + block_text + "\n\n" + text[insert_at:].lstrip("\n")
        else:
            chapter = next((row for row in _heading_rows(text) if row["level"] == "chapter"), None)
            section_level = "section" if chapter else "section"
            insert_at = _heading_scope_end(text, _heading_rows(text), chapter) if chapter else len(text)
            name = str(heritage.get("title") or heritage.get("name") or "Unnamed Heritage")
            block_text = f"\\{section_level}{{Heritages}}\n" + _heritage_block_text("subsection", heritage)
            text = text[:insert_at].rstrip() + "\n\n" + block_text + "\n\n" + text[insert_at:].lstrip("\n")
        changes.append(f"added heritage {heritage.get('title') or heritage.get('name') or 'heritage'}")
    return text, changes


def _replace_source_label(text: str, labels: list[str], value: str) -> tuple[str, bool]:
    if value is None:
        return text, False
    alternates = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(
        r"(\\(?:textbf|textit|emph)\s*\{\s*(?:" + alternates + r")\s*:?\s*\}\s*:?\s*)(.*?)(?=(?:\\\\)|(?:\r?\n\s*\r?\n)|(?:\\(?:part|chapter|section|subsection|subsubsection|begin|end)\b)|$)",
        re.I | re.S,
    )
    match = pattern.search(text)
    if not match:
        return text, False
    replacement = match.group(1) + latex_escape(value).strip()
    return text[:match.start()] + replacement + text[match.end():], True


def _display_size(value: str) -> str:
    return {"tiny": "Tiny", "sm": "Small", "small": "Small", "med": "Medium", "medium": "Medium", "lg": "Large", "large": "Large", "huge": "Huge", "grg": "Gargantuan", "gargantuan": "Gargantuan"}.get(str(value or "").strip().lower(), str(value or "").strip())


def _display_vision(value: str) -> str:
    return {"normal": "Normal", "darkvision": "Darkvision", "low-light-vision": "Low-Light Vision"}.get(str(value or "").strip().lower(), str(value or "").strip())


def _ancestry_snapshot_from_payload(payload: dict) -> dict:
    return {key: payload.get(key, "") for key in (
        "ancestry_hp", "ancestry_size", "ancestry_speed", "ancestry_reach", "ancestry_vision",
        "ancestry_languages", "ancestry_additional_languages", "ancestry_traits", "ancestry_boosts",
        "ancestry_free_boosts", "ancestry_flaws",
    )}


def _sync_ancestry_chassis(text: str, payload: dict, previous: dict) -> tuple[str, list[str]]:
    changes: list[str] = []
    current = _ancestry_snapshot_from_payload(payload)
    fields = [
        ("ancestry_hp", ["Hitpoints", "Hit Points", "HP"], lambda v: str(v).strip()),
        ("ancestry_size", ["Size"], _display_size),
        ("ancestry_speed", ["Speed"], lambda v: (str(v).strip() + " feet") if str(v).strip().isdigit() else str(v).strip()),
        ("ancestry_reach", ["Reach"], lambda v: (str(v).strip() + " feet") if str(v).strip().isdigit() else str(v).strip()),
        ("ancestry_vision", ["Vision", "Senses"], _display_vision),
        ("ancestry_languages", ["Languages"], lambda v: str(v).strip()),
        ("ancestry_traits", ["Traits"], lambda v: str(v).strip()),
        ("ancestry_flaws", ["Ability Flaw", "Ability Flaws"], lambda v: str(v).strip()),
    ]
    for key, labels, formatter in fields:
        if str(current.get(key, "")) == str(previous.get(key, "")):
            continue
        text, changed = _replace_source_label(text, labels, formatter(current.get(key, "")))
        if changed:
            changes.append(f"updated {labels[0]}")
    if str(current.get("ancestry_boosts", "")) != str(previous.get("ancestry_boosts", "")) or str(current.get("ancestry_free_boosts", "")) != str(previous.get("ancestry_free_boosts", "")):
        boosts = [x.strip() for x in str(current.get("ancestry_boosts") or "").split(",") if x.strip()]
        try:
            free = max(0, int(current.get("ancestry_free_boosts") or 0))
        except (TypeError, ValueError):
            free = 0
        boosts.extend(["Free"] * free)
        text, changed = _replace_source_label(text, ["Ability Boost", "Ability Boosts"], ", ".join(boosts))
        if changed:
            changes.append("updated Ability Boosts")
    return text, changes


def _promote_source_link_metadata(payload: dict) -> None:
    rules = payload.get("bundle_feats") if isinstance(payload.get("bundle_feats"), list) else []
    for rule in rules:
        if isinstance(rule, dict):
            rule["_source_original_title"] = str(rule.get("title") or "").strip()
            try:
                rule["_source_original_level"] = int(rule.get("level") or 0)
            except (TypeError, ValueError):
                rule["_source_original_level"] = 0
    heritages = payload.get("heritages") if isinstance(payload.get("heritages"), list) else []
    for row in heritages:
        if isinstance(row, dict):
            row["_source_original_title"] = str(row.get("title") or row.get("name") or "").strip()
    payload["source_link_snapshot"] = {
        "title": str(payload.get("source_link_current_title") or payload.get("source_link_original_title") or "").strip(),
        "ancestry": _ancestry_snapshot_from_payload(payload),
        "bundle_feats": [dict(rule) for rule in rules if isinstance(rule, dict)],
        "heritages": [dict(row) for row in heritages if isinstance(row, dict)],
        "dedication": {key: payload.get(key, "") for key in (
            "dedication_title", "dedication_level", "dedication_action_cost", "dedication_traits", "dedication_prerequisites",
            "dedication_frequency", "dedication_trigger", "dedication_requirements", "dedication_special", "dedication_description",
        )},
    }


def sync_source_linked_bundle_text(existing: str, row: dict) -> tuple[str, dict, list[str]]:
    """Apply a source-linked Forge ancestry/archetype back to its classified .tex.

    Existing rule commands are updated in place whenever possible. New feats are
    inserted into the matching level heading, and a missing level heading is
    created using the file's existing heading style.
    """
    payload = dict(row.get("payload") or {})
    document = str(payload.get("homebrew_document") or "").strip().lower()
    if document not in {"ancestry", "archetype"} or not truthy(payload.get("source_linked")):
        return existing, payload, []
    previous = payload.get("source_link_snapshot") if isinstance(payload.get("source_link_snapshot"), dict) else {}
    changes: list[str] = []
    text = existing

    old_title = str(payload.get("source_link_original_title") or previous.get("title") or row.get("title") or "").strip()
    new_title = str(row.get("title") or old_title).strip()
    if new_title and old_title and new_title != old_title:
        chapter_pattern = re.compile(r"(\\chapter\*?\s*\{)" + re.escape(old_title) + r"(\})", re.I)
        text, count = chapter_pattern.subn(lambda m: m.group(1) + latex_escape(new_title) + m.group(2), text, count=1)
        if count:
            changes.append(f"renamed chapter to {new_title}")
            payload["source_link_original_title"] = new_title
    payload["source_link_current_title"] = new_title

    if document == "ancestry":
        text, chassis_changes = _sync_ancestry_chassis(text, payload, previous.get("ancestry") if isinstance(previous.get("ancestry"), dict) else {})
        changes.extend(chassis_changes)
        text, heritage_changes = _sync_heritages(
            text,
            [dict(x) for x in payload.get("heritages", []) if isinstance(x, dict)],
            [dict(x) for x in previous.get("heritages", []) if isinstance(x, dict)],
        )
        changes.extend(heritage_changes)

    previous_rules = [dict(x) for x in previous.get("bundle_feats", []) if isinstance(x, dict)]
    previous_by_origin = {_source_key(str(x.get("_source_original_title") or x.get("title") or "")): x for x in previous_rules}
    current_rules = [dict(x) for x in payload.get("bundle_feats", []) if isinstance(x, dict)]
    current_origins = {_source_key(str(x.get("_source_original_title") or "")) for x in current_rules if x.get("_source_original_title")}
    for old in previous_rules:
        original = str(old.get("_source_original_title") or old.get("title") or "").strip()
        if original and _source_key(original) not in current_origins:
            text, removed = _remove_source_feat(text, original)
            if removed:
                changes.append(f"removed feat {original}")
    for rule in current_rules:
        original = str(rule.get("_source_original_title") or "").strip()
        old = previous_by_origin.get(_source_key(original)) if original else None
        if old and _rule_compare(old) == _rule_compare(rule):
            continue
        text, rule_changes = _replace_or_move_rule(text, rule, old)
        changes.extend(rule_changes)

    if document == "archetype":
        dedication = {
            "kind": "feat",
            "title": str(payload.get("dedication_title") or f"{new_title} Dedication"),
            "level": int(payload.get("dedication_level") or 2),
            "traits": str(payload.get("dedication_traits") or "archetype, dedication"),
            "action_cost": str(payload.get("dedication_action_cost") or ""),
            "prerequisites": str(payload.get("dedication_prerequisites") or ""),
            "frequency": str(payload.get("dedication_frequency") or ""),
            "trigger": str(payload.get("dedication_trigger") or ""),
            "requirements": str(payload.get("dedication_requirements") or ""),
            "special": str(payload.get("dedication_special") or ""),
            "description": str(payload.get("dedication_description") or ""),
        }
        old_ded = previous.get("dedication") if isinstance(previous.get("dedication"), dict) else {}
        old_title = str(old_ded.get("dedication_title") or old_ded.get("title") or dedication["title"]).strip()
        found = _find_command_by_title(text, "feat", old_title, 4)
        if found and {k: str(old_ded.get(k, "")) for k in old_ded} != {k: str(payload.get(k, "")) for k in old_ded}:
            text = text[:found["start"]] + _bundle_rule_latex(dedication).rstrip() + text[found["end"]:]
            changes.append(f"updated dedication {dedication['title']}")

    _promote_source_link_metadata(payload)
    payload["source_link_snapshot"]["title"] = new_title
    return text, payload, changes
