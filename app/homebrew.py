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
