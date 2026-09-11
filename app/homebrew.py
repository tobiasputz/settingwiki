from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

NON_MONSTER_KINDS = {"item", "feat", "action", "homebrew"}
HOME_BREW_SECTIONS = {
    "ancestry": "Ancestry Feats",
    "archetype": "Archetype Feats",
    "class": "Class Feats",
    "general": "General & Skill Feats",
    "actions": "Actions & Activities",
    "items": "Items & Equipment",
    "other": "Other Homebrew",
}


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_homebrew_source_path(path: str | None) -> bool:
    parts = [p.casefold() for p in PurePosixPath(str(path or "").replace("\\", "/")).parts]
    return bool(parts and parts[0] in {"homebrew", "home-brew", "custom"})


def source_homebrew_bucket(path: str | None) -> tuple[str, str]:
    parts = list(PurePosixPath(str(path or "").replace("\\", "/")).parts)
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

    if kind == "homebrew" and document in {"feat", "action", "equipment", "item", "weapon", "armor", "consumable"}:
        effective = "action" if document == "action" else "feat" if document == "feat" else "item"
    else:
        effective = kind

    if explicit in HOME_BREW_SECTIONS:
        section = explicit
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
        if section == "ancestry": group = str(payload.get("ancestry_trait") or "").strip()
        elif section == "archetype": group = str(payload.get("archetype_name") or "").strip()
        elif section == "class": group = str(payload.get("class_name") or "").strip()
        elif section == "items": group = str(payload.get("item_type") or "Equipment").strip().replace("_", " ").title()
        elif section == "actions": group = "Actions & Activities"
        elif section == "general": group = str(payload.get("feat_category") or "General").strip().title()
    if not group:
        # A PF2e ancestry/archetype/class name is normally also a trait. Prefer a
        # non-generic trait as a useful automatic guess, but keep it fully editable.
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
    for label,key in (("Prerequisites","prerequisites"),("Trigger","trigger"),("Requirements","requirements"),("Frequency","frequency")):
        value=str(payload.get(key) or "").strip()
        if value: lines.append(r"\textbf{"+label+":} "+latex_escape(value)+r"\\")
    desc=str(payload.get("description") or "").strip() or str(row.get("summary") or "").strip()
    if desc: lines.append(latex_escape(desc).replace("\n", "\n\n"))
    return "\n".join(lines).strip()


def homebrew_latex_snippet(row: dict) -> str:
    payload=dict(row.get("payload") or {})
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


def upsert_latex_block(existing: str, entry_id: int, snippet: str) -> str:
    start=f"% SEEKER-HOMEBREW:{int(entry_id)}:BEGIN"
    end=f"% SEEKER-HOMEBREW:{int(entry_id)}:END"
    block=f"{start}\n{snippet.rstrip()}\n{end}"
    pattern=re.compile(re.escape(start)+r".*?"+re.escape(end), re.S)
    if pattern.search(existing):
        return pattern.sub(lambda _m:block, existing)
    prefix=existing.rstrip()
    return (prefix+"\n\n" if prefix else "")+block+"\n"
