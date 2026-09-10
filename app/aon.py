from __future__ import annotations

import asyncio
import html as html_lib
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

AON_HOSTS = {"2e.aonprd.com", "www.2e.aonprd.com"}
AON_PATHS = {"/monsters.aspx", "/npcs.aspx"}
AON_QUERY_KEYS = {"id", "elite", "weak", "pwl", "noredirect", "redirected"}
AON_MAX_LINKS = 25
AON_MAX_BYTES = 2_500_000
AON_TIMEOUT = httpx.Timeout(12.0, connect=5.0)
AON_USER_AGENT = "Seeker/7.1.0 (+Archives-of-Nethys creature importer; private campaign tool)"

_ACTION_WORDS = {
    "one-action": "1",
    "single-action": "1",
    "two-actions": "2",
    "three-actions": "3",
    "reaction": "reaction",
    "free-action": "free",
}
_SIZE = {
    "tiny": "tiny",
    "small": "sm",
    "medium": "med",
    "large": "lg",
    "huge": "huge",
    "gargantuan": "grg",
}
_RARITIES = {"common", "uncommon", "rare", "unique"}
_ALIGNMENTS = {"lg", "ng", "cg", "ln", "n", "cn", "le", "ne", "ce"}
_DAMAGE_TYPES = {
    "acid", "bleed", "bludgeoning", "cold", "electricity", "fire", "force", "mental", "piercing",
    "poison", "slashing", "sonic", "spirit", "vitality", "void",
}
_CASTING_RE = re.compile(
    r"\b(?P<tradition>Arcane|Divine|Occult|Primal)\s+(?P<mode>Innate|Prepared|Spontaneous|Focus)\s+Spells?\b"
    r"(?:\s+DC\s*(?P<dc>\d+))?(?:\s*,?\s*attack\s*\+?(?P<attack>-?\d+))?",
    re.I,
)
_ATTACK_RE = re.compile(r"\b(?P<type>Melee|Ranged)\s*\[(?P<actions>one-action|two-actions|three-actions)\]\s*", re.I)
_ABILITY_RE = re.compile(
    r"(?<![\w])(?P<name>[A-Z][A-Za-z0-9À-ÖØ-öø-ÿ'’\-–—,: ]{1,72}?)\s*"
    r"\[(?P<actions>one-action|two-actions|three-actions|reaction|free-action)\]",
)


class AoNImportError(ValueError):
    pass


@dataclass
class AoNFetchResult:
    url: str
    parsed: dict[str, Any] | None = None
    error: str = ""


def normalize_aon_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise AoNImportError("Paste an Archives of Nethys creature link.")
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.lstrip("/")
    try:
        parts = urlsplit(value)
    except Exception as exc:
        raise AoNImportError("That is not a valid URL.") from exc
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in AON_HOSTS:
        raise AoNImportError("Only creature links from 2e.aonprd.com can be imported.")
    path = (parts.path or "").lower()
    if path not in AON_PATHS:
        raise AoNImportError("Use an Archives of Nethys Monsters.aspx or NPCs.aspx creature page.")
    query = []
    creature_id = None
    for key, val in parse_qsl(parts.query, keep_blank_values=False):
        kl = key.lower()
        if kl not in AON_QUERY_KEYS:
            continue
        if kl == "id":
            if not str(val).isdigit():
                raise AoNImportError("The Archives of Nethys link is missing a numeric creature ID.")
            creature_id = str(int(val))
            query.append(("ID", creature_id))
        elif kl in {"elite", "weak", "pwl"}:
            if str(val).strip().lower() in {"1", "true", "yes", "on"}:
                query.append((key.title() if kl != "pwl" else "PWL", "true"))
        elif kl in {"noredirect", "redirected"}:
            query.append(("NoRedirect" if kl == "noredirect" else "Redirected", "1"))
    if not creature_id:
        raise AoNImportError("The Archives of Nethys link is missing ?ID=…")
    # Stable ordering makes duplicate detection deterministic while preserving explicit variants.
    query.sort(key=lambda kv: (0 if kv[0] == "ID" else 1, kv[0].lower()))
    canonical_path = "/Monsters.aspx" if path == "/monsters.aspx" else "/NPCs.aspx"
    return urlunsplit(("https", "2e.aonprd.com", canonical_path, urlencode(query), ""))


def _clean_text(value: str) -> str:
    text = html_lib.unescape(str(value or ""))
    text = text.replace("−", "-").replace("–", "-").replace("—", "-").replace("×", "x")
    text = re.sub(r"\s+", " ", text).strip()
    return text


_AON_CHROME_MARKERS = (
    "Home Actions/Activities Afflictions Ancestries Archetypes",
    "Archives of Nethys Paizo & Archives of Nethys",
    "Maximize Menu Archives of Nethys",
    "Character Creation + Ancestries Archetypes Backgrounds Classes",
    "All Creatures Abilities | Monsters | NPCs",
    "Licenses Sources Contact Us Contributors Support the Archives",
)


def sanitize_aon_summary(value: str, *, title: str = "") -> str:
    """Return only creature prose, never Archives of Nethys navigation chrome.

    AoN has shipped several HTML layouts over time and some pages expose a meta
    description containing the site's entire responsive navigation.  Treating
    that as creature lore is both ugly and potentially huge.  This helper is
    intentionally conservative: when a value looks like site chrome, retain the
    useful no-description sentinel if present and otherwise discard it.
    """
    text = _clean_text(value)
    if not text:
        return ""
    no_description = re.search(r"This creature did not include a description\.?", text, re.I)
    chrome_hits = sum(marker.lower() in text.lower() for marker in _AON_CHROME_MARKERS)
    # A single very distinctive marker is enough; long strings with several
    # weaker markers are definitely navigation rather than authored creature text.
    if chrome_hits >= 1 or (len(text) > 700 and "archives of nethys" in text.lower() and "support the archives" in text.lower()):
        return _clean_text(no_description.group(0)) if no_description else ""
    # Remove common adjustment/navigation tails that can leak into an otherwise
    # valid short excerpt.
    text = re.sub(r"\s+(?:Elite\s*\|\s*Normal(?:\s*\|\s*Weak)?|Weak\s*\|\s*Normal)\s*\|?\s*$", "", text, flags=re.I)
    if title:
        # Some metadata starts by repeating the page title; one repetition is
        # harmless but adds no information.
        text = re.sub(rf"^{re.escape(_clean_text(title))}\s*[-:|]?\s*", "", text, count=1, flags=re.I)
    return _clean_text(text)[:1800]


def _action_marker(tag) -> str:
    hay = " ".join(
        str(x or "") for x in [tag.get("alt"), tag.get("title"), " ".join(tag.get("class") or [])]
    ).lower()
    if "reaction" in hay:
        return " [reaction] "
    if "free action" in hay or "free-action" in hay or "action-free" in hay:
        return " [free-action] "
    if "three action" in hay or "three-action" in hay or "action-three" in hay:
        return " [three-actions] "
    if "two action" in hay or "two-action" in hay or "action-two" in hay:
        return " [two-actions] "
    if "one action" in hay or "single action" in hay or "one-action" in hay or "action-one" in hay:
        return " [one-action] "
    return ""


def _content_text(soup: BeautifulSoup) -> tuple[str, str]:
    content = soup.find(id="ctl00_MainContent_DetailedOutput") or soup.find(id="ctl00_RadDrawer1_Content_MainContent_DetailedOutput")
    if content is None:
        content = soup.find("main") or soup.body or soup
    # Work on a detached copy so inserting glyph text cannot alter later metadata lookups.
    clone = BeautifulSoup(str(content), "html.parser")
    for tag in clone.find_all(["script", "style", "noscript", "form", "button"]):
        tag.decompose()
    for tag in clone.find_all(["img", "span", "i"]):
        marker = _action_marker(tag)
        if marker:
            tag.insert_before(marker)
    flat = _clean_text(clone.get_text(" ", strip=True))
    # A line-preserving variant is useful for passive ability fallback parsing.
    for br in clone.find_all(["br", "hr", "p", "div", "li", "h1", "h2", "h3", "h4"]):
        br.insert_after("\n")
    lined = html_lib.unescape(clone.get_text(" ", strip=False)).replace("\r", "")
    lined = "\n".join(_clean_text(line) for line in lined.split("\n") if _clean_text(line))
    return flat, lined


def _page_title(soup: BeautifulSoup) -> str:
    raw = _clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    if raw:
        raw = re.sub(r"\s+-\s+(?:Monsters|NPCs).*?$", "", raw, flags=re.I)
        raw = re.sub(r"\s+-\s+Archives of Nethys.*$", "", raw, flags=re.I)
    if raw:
        return raw
    h1 = soup.find("h1", class_=re.compile(r"title", re.I)) or soup.find("h1")
    if not h1:
        return "Imported creature"
    return re.sub(r"\s*Creature\s*-?\d+\s*$", "", _clean_text(h1.get_text(" ", strip=True)), flags=re.I).strip() or "Imported creature"


def _meta_description(soup: BeautifulSoup) -> str:
    tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if not tag:
        return ""
    raw = str(tag.get("content") or "")
    # AoN sometimes stores HTML inside description metadata.
    return sanitize_aon_summary(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True), title=_page_title(soup))


def _split_outside_parens(text: str, delimiter: str = ",") -> list[str]:
    rows: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch == delimiter and depth == 0:
            rows.append(text[start:idx].strip())
            start = idx + 1
    rows.append(text[start:].strip())
    return [x for x in rows if x]


def _extract_rank_groups(body: str) -> list[dict[str, Any]]:
    marker = re.compile(
        r"(?:(?P<rank>\d+)(?:st|nd|rd|th)|Cantrips?\s*\((?P<cantrip>\d+)(?:st|nd|rd|th)\)|Constant\s*\((?P<constant>\d+)(?:st|nd|rd|th)\))\s+",
        re.I,
    )
    matches = list(marker.finditer(body))
    out: list[dict[str, Any]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        raw = body[m.end():end].strip(" ;")
        if not raw:
            continue
        rank = 0 if m.group("cantrip") else int(m.group("rank") or m.group("constant") or 1)
        usage = "cantrip" if m.group("cantrip") else "constant" if m.group("constant") else "normal"
        # Group-wide slot annotations should not become spell names.
        raw = re.sub(r"\s*\(\s*\d+\s+slots?\s*\)\s*$", "", raw, flags=re.I)
        for chunk in _split_outside_parens(raw):
            name = chunk.strip().strip(".;")
            if not name:
                continue
            notes = ""
            pm = re.search(r"\(([^()]*)\)\s*$", name)
            if pm:
                notes = pm.group(1).strip()
                name = name[:pm.start()].strip()
            uses = 1
            if re.search(r"\bat\s+will\b", notes, re.I):
                uses = 999
            else:
                um = re.search(r"(?:x|×)\s*(\d+)", notes, re.I)
                if um:
                    uses = max(1, min(99, int(um.group(1))))
            if not name:
                continue
            out.append({
                "name": name,
                "rank": rank,
                "actions": "2",
                "uses": uses,
                "source_uuid": "",
                "aon_usage": usage,
                "aon_notes": notes,
            })
    return out


def _parse_spellcasting(text: str) -> list[dict[str, Any]]:
    matches = list(_CASTING_RE.finditer(text))
    out: list[dict[str, Any]] = []
    for i, m in enumerate(matches):
        # Stop at the next casting block or the next clearly marked action/attack.
        candidates = [len(text)]
        if i + 1 < len(matches):
            candidates.append(matches[i + 1].start())
        am = _ABILITY_RE.search(text, m.end())
        if am:
            candidates.append(am.start())
        atk = _ATTACK_RE.search(text, m.end())
        if atk:
            candidates.append(atk.start())
        end = min(c for c in candidates if c > m.start())
        body = text[m.end():end].strip(" ;")
        out.append({
            "tradition": m.group("tradition").lower(),
            "mode": m.group("mode").lower(),
            "dc": int(m.group("dc") or 0),
            "attack": int(m.group("attack")) if m.group("attack") is not None else None,
            "label": _clean_text(m.group(0)),
            "spells": _extract_rank_groups(body),
        })
    return out


def _damage_components(raw: str) -> tuple[list[dict[str, Any]], str]:
    components: list[dict[str, Any]] = []
    # Covers 2d8+4, 3d6+2+15, 1d4-1 and flat damage such as 6 fire.
    damage_re = re.compile(
        r"(?P<formula>(?:\d+d\d+(?:\s*[+-]\s*\d+)*|\d+))\s+(?:(?P<persistent>persistent)\s+)?(?P<type>acid|bleed|bludgeoning|cold|electricity|fire|force|mental|piercing|poison|slashing|sonic|spirit|vitality|void)\b",
        re.I,
    )
    spans = []
    for m in damage_re.finditer(raw):
        formula = re.sub(r"\s+", "", m.group("formula"))
        dtype = m.group("type").lower()
        category = "persistent" if m.group("persistent") or dtype == "bleed" and "persistent" in m.group(0).lower() else None
        components.append({"formula": formula, "type": dtype, "category": category})
        spans.append(m.span())
    remainder = raw
    for start, end in reversed(spans):
        remainder = remainder[:start] + " " + remainder[end:]
    remainder = re.sub(r"\b(?:Damage|plus|and)\b", " ", remainder, flags=re.I)
    remainder = re.sub(r"[;,]+", ", ", remainder)
    remainder = _clean_text(remainder).strip(" ,.;")
    return components, remainder


def _parse_attack(chunk: str, marker: re.Match[str]) -> dict[str, Any] | None:
    body = chunk[marker.end() - marker.start():].strip() if marker.start() == 0 else chunk
    # The chunk passed by parse_aon_text normally begins at marker.start().
    body = re.sub(r"^(?:Melee|Ranged)\s*\[(?:one-action|two-actions|three-actions)\]\s*", "", body, flags=re.I)
    m = re.match(r"(?P<name>.+?)\s+\+(?P<bonus>-?\d+)\s*(?:\[[^\]]+\])?\s*(?P<rest>.*)$", body)
    if not m:
        return None
    rest = m.group("rest").strip()
    traits = ""
    tm = re.match(r"\(([^)]*)\)\s*,?\s*(.*)$", rest)
    if tm:
        traits = tm.group(1).strip()
        rest = tm.group(2).strip()
    range_value = ""
    rm = re.search(r"\brange\s+(\d+)\s*(?:feet|ft\.?)(?:\b|$)", traits, re.I)
    if rm:
        range_value = rm.group(1)
    # Normalize reach 10 feet into the PF2e NPC attack trait slug form.
    trait_parts = []
    for t in _split_outside_parens(traits):
        t = re.sub(r"\breach\s+(\d+)\s*(?:feet|ft\.?)", r"reach-\1", t, flags=re.I)
        if not re.match(r"^range\s+\d+", t, re.I):
            trait_parts.append(t)
    damage_tail = rest
    dm = re.search(r"\bDamage\s+(.+)$", rest, re.I)
    if dm:
        damage_tail = dm.group(1)
    components, effects = _damage_components(damage_tail)
    first = components[0] if components else {"formula": "1d4", "type": "bludgeoning", "category": None}
    # Residual prose is usually an attack effect such as Grab/Knockdown.
    effects = re.sub(r"^\s*(?:plus|and)\s+", "", effects, flags=re.I).strip(" ,.;")
    return {
        "name": _clean_text(m.group("name"))[:120],
        "type": marker.group("type").lower(),
        "bonus": int(m.group("bonus")),
        "damage": first["formula"],
        "damage_type": first["type"],
        "damage_components": components,
        "range": int(range_value) if range_value else "",
        "traits": ", ".join(trait_parts),
        "effects": effects,
    }


def _parse_ability(chunk: str, marker: re.Match[str]) -> dict[str, Any] | None:
    name = _clean_text(marker.group("name")).strip(" ,.;")
    if name.lower() in {"melee", "ranged"}:
        return None
    action = _ACTION_WORDS.get(marker.group("actions").lower(), "")
    body = chunk[marker.end() - marker.start():].strip() if marker.start() == 0 else chunk
    body = re.sub(r"^[A-Z][A-Za-z0-9À-ÖØ-öø-ÿ'’\-–—,: ]{1,72}?\s*\[(?:one-action|two-actions|three-actions|reaction|free-action)\]\s*", "", body).strip()
    traits = ""
    tm = re.match(r"\(([^)]*)\)\s*(.*)$", body)
    if tm:
        traits, body = tm.group(1).strip(), tm.group(2).strip()
    trigger = requirements = ""
    trig = re.search(r"\bTrigger\s+(.+?)(?=\s+(?:Requirements|Effect)\b|$)", body, re.I)
    req = re.search(r"\bRequirements?\s+(.+?)(?=\s+(?:Trigger|Effect)\b|$)", body, re.I)
    if trig:
        trigger = trig.group(1).strip(" ;")
    if req:
        requirements = req.group(1).strip(" ;")
    description = re.sub(r"\bTrigger\s+.+?(?=\s+(?:Requirements|Effect)\b|$)", "", body, flags=re.I)
    description = re.sub(r"\bRequirements?\s+.+?(?=\s+(?:Trigger|Effect)\b|$)", "", description, flags=re.I)
    description = re.sub(r"^\s*Effect\s+", "", description, flags=re.I).strip(" ;")
    dc = ""
    dc_type = ""
    dm = re.search(r"\bDC\s*(\d+)\s+(Fortitude|Reflex|Will)\b|\b(Fortitude|Reflex|Will)\s+(?:save\s+)?(?:against\s+)?DC\s*(\d+)", body, re.I)
    if dm:
        dc = int(dm.group(1) or dm.group(4))
        dc_type = (dm.group(2) or dm.group(3)).lower()
    dmg = ""
    dtype = ""
    cm = re.search(r"(?P<formula>\d+d\d+(?:\s*[+-]\s*\d+)*)\s+(?P<type>acid|bleed|bludgeoning|cold|electricity|fire|force|mental|piercing|poison|slashing|sonic|spirit|vitality|void)\s+damage", body, re.I)
    if cm:
        dmg = re.sub(r"\s+", "", cm.group("formula")); dtype = cm.group("type").lower()
    return {
        "name": name[:160], "actions": action, "category": "offensive", "traits": traits,
        "trigger": trigger, "requirements": requirements, "dc_type": dc_type, "dc": dc,
        "dc_basic": bool(dc and re.search(r"\bbasic\b", body, re.I)), "dc_show": "owner",
        "damage": dmg, "damage_type": dtype or "bludgeoning", "description": description[:8000],
    }


def _parse_speed(raw: str) -> tuple[int, list[dict[str, Any]], str]:
    base = 25
    others: list[dict[str, Any]] = []
    details = _clean_text(raw)
    for idx, part in enumerate(_split_outside_parens(details)):
        m = re.search(r"(?:(?P<type>burrow|climb|fly|swim)\s+)?(?P<value>\d+)\s*(?:feet|ft\.?)", part, re.I)
        if not m:
            continue
        typ = (m.group("type") or "land").lower()
        val = int(m.group("value"))
        if typ == "land" and idx == 0:
            base = val
        elif typ == "land" and base == 25:
            base = val
        else:
            others.append({"type": typ, "value": val})
    return base, others, details


def _extract_field(text: str, start_pat: str, end_pats: list[str]) -> str:
    end = "|".join(f"(?:{x})" for x in end_pats)
    m = re.search(rf"(?:{start_pat})\s*(.*?)(?=\s+(?:{end})\b|$)", text, re.I)
    return _clean_text(m.group(1)) if m else ""


def parse_aon_text(text: str, *, title: str = "", summary: str = "", url: str = "") -> dict[str, Any]:
    text = _clean_text(text)
    if not text:
        raise AoNImportError("Archives of Nethys returned an empty creature page.")
    title = _clean_text(title) or "Imported creature"

    # Prefer a header matching the page title, but gracefully accept adjusted names.
    header_re = re.compile(r"(?:(?:Elite|Weak)\s+)?(?P<name>[A-Z][A-Za-z0-9À-ÖØ-öø-ÿ'’\-–—,: ]{1,100}?)\s*Creature\s*(?P<level>-?\d+)", re.I)
    headers = list(header_re.finditer(text))
    if not headers:
        raise AoNImportError("Seeker could not find a PF2e creature stat block on that page.")
    # AoN pages can repeat the normal page name before the actual adjusted statblock. Pick the first header with Source/Perception after it.
    header = headers[0]
    for cand in headers:
        tail = text[cand.end():cand.end()+1400]
        if re.search(r"\bSource\b", tail, re.I) and re.search(r"\bPerception\b", tail, re.I):
            header = cand; break
    name = _clean_text(header.group("name"))
    # Page title is generally cleaner than a header polluted by legacy/adjustment prose.
    if title and title.lower() not in {"archives of nethys", "imported creature"}:
        clean_title = re.sub(r"^(?:Elite|Weak)\s+", "", title, flags=re.I).strip()
        if clean_title and len(clean_title) <= 140:
            name = clean_title if not re.match(r"^(?:Elite|Weak)\b", header.group(0), re.I) else _clean_text(header.group("name"))
    level = int(header.group("level"))
    stat = text[header.end():]
    for marker in (" All Monsters in ", " Image: Sidebar ", " Site Owner ", " Copyright "):
        pos = stat.find(marker)
        if pos >= 0:
            stat = stat[:pos]

    source = ""
    source_page = ""
    sm = re.search(r"\bSource\s+(.+?)\s+pg\.\s*(\d+)\b", stat, re.I)
    if sm:
        source, source_page = _clean_text(sm.group(1)), sm.group(2)
    pre_source = stat[:sm.start()] if sm else ""
    pre_source = re.sub(r"\bLegacy Content\b", " ", pre_source, flags=re.I)
    tokens = [t.strip(" ,.;") for t in pre_source.split() if t.strip(" ,.;")]
    rarity = "common"
    size = "med"
    traits: list[str] = []
    for token in tokens:
        low = token.lower()
        if low in _RARITIES:
            rarity = low; continue
        if low in _SIZE:
            size = _SIZE[low]; continue
        if low in _ALIGNMENTS or low in {"elite", "weak"}:
            continue
        if re.match(r"^[A-Za-z][A-Za-z'’-]*$", token) and token.lower() not in {"source", "content"}:
            traits.append(token)
    # Deduplicate while preserving AoN order.
    traits = list(dict.fromkeys(traits))

    perception = 0; senses = ""
    pm = re.search(r"\bPerception\s*\+?(-?\d+)(?:\s*;\s*(.*?))?(?=\s+(?:Languages|Skills|Str\b|Items\b|AC\b))", stat, re.I)
    if pm:
        perception = int(pm.group(1)); senses = _clean_text(pm.group(2) or "")
    languages = _extract_field(stat, r"Languages", [r"Skills", r"Str", r"Items", r"AC"])
    # Telepathy and similar communication riders remain useful in the Languages details field.
    skills = _extract_field(stat, r"Skills", [r"Str", r"Items", r"AC"])

    abilities = {k: 0 for k in ("str", "dex", "con", "int", "wis", "cha")}
    am = re.search(r"\bStr\s*([+-]?\d+)\s*,\s*Dex\s*([+-]?\d+)\s*,\s*Con\s*([+-]?\d+)\s*,\s*Int\s*([+-]?\d+)\s*,\s*Wis\s*([+-]?\d+)\s*,\s*Cha\s*([+-]?\d+)", stat, re.I)
    if am:
        for key, val in zip(abilities, am.groups()): abilities[key] = int(val)

    ac = fort = reflex = will = 0
    dm = re.search(r"\bAC\s*(\d+).*?\bFort\s*\+?(-?\d+)\s*,\s*Ref\s*\+?(-?\d+)\s*,\s*Will\s*\+?(-?\d+)", stat, re.I)
    if dm:
        ac, fort, reflex, will = (int(x) for x in dm.groups())
    hp = 1
    hm = re.search(r"\bHP\s*(\d+)\b(?P<tail>.*?)(?=\s+Speed\b|\s+(?:Melee|Ranged)\s*\[|$)", stat, re.I)
    hp_tail = ""
    if hm:
        hp = max(1, int(hm.group(1))); hp_tail = _clean_text(hm.group("tail"))
    immunities = _extract_field(hp_tail, r"Immunities", [r"Weaknesses", r"Resistances"])
    weaknesses = _extract_field(hp_tail, r"Weaknesses", [r"Immunities", r"Resistances"])
    resistances = _extract_field(hp_tail, r"Resistances", [r"Immunities", r"Weaknesses"])

    speed_text = _extract_field(stat, r"Speed", [r"Melee", r"Ranged", r"Arcane", r"Divine", r"Occult", r"Primal", r"Rituals"])
    speed, other_speeds, speed_details = _parse_speed(speed_text)

    # Build a token stream over offense/action markers so adjacent AoN entries (which sometimes have no whitespace after an effect) split safely.
    markers: list[tuple[int, str, re.Match[str]]] = []
    for m in _ATTACK_RE.finditer(stat): markers.append((m.start(), "attack", m))
    for m in _CASTING_RE.finditer(stat): markers.append((m.start(), "casting", m))
    for m in _ABILITY_RE.finditer(stat):
        if m.group("name").strip().lower() not in {"melee", "ranged"}:
            markers.append((m.start(), "ability", m))
    markers.sort(key=lambda row: row[0])
    # De-duplicate markers that fall inside a longer marker at the same position.
    compact: list[tuple[int, str, re.Match[str]]] = []
    seen_starts: set[tuple[int, str]] = set()
    for row in markers:
        key = (row[0], row[1])
        if key not in seen_starts:
            compact.append(row); seen_starts.add(key)
    markers = compact

    attacks: list[dict[str, Any]] = []
    special: list[dict[str, Any]] = []
    # Parse attacks/actions from their own spans; casting is parsed separately to preserve rank groups.
    for idx, (start, kind, marker) in enumerate(markers):
        if kind == "casting":
            continue
        end = len(stat)
        for nstart, nkind, _nm in markers[idx + 1:]:
            if nstart > start:
                end = nstart; break
        chunk = stat[start:end].strip()
        local_marker = (_ATTACK_RE if kind == "attack" else _ABILITY_RE).match(chunk)
        if not local_marker:
            continue
        if kind == "attack":
            row = _parse_attack(chunk, local_marker)
            if row: attacks.append(row)
        else:
            row = _parse_ability(chunk, local_marker)
            if row: special.append(row)

    casting_entries = _parse_spellcasting(stat)
    primary_cast = casting_entries[0] if casting_entries else {}
    spells: list[dict[str, Any]] = []
    for cast in casting_entries:
        spells.extend(cast.get("spells") or [])

    # If AoN supplied no meta description, use a short pre-statblock excerpt while avoiding Recall Knowledge/navigation text.
    summary = sanitize_aon_summary(summary, title=title)
    if not summary:
        prefix = text[:header.start()]
        prefix = re.sub(r".*?\b(?:Elite\s*\|\s*Normal\s*\|\s*Weak|Proficiency without Level)\b", "", prefix, flags=re.I)
        summary = sanitize_aon_summary(_clean_text(prefix)[-1200:], title=title)
    if not summary:
        summary = "This creature did not include a description."

    payload: dict[str, Any] = {
        "level": level,
        "rarity": rarity,
        "size": size,
        "actor_role": "npc",
        "traits": ", ".join(traits),
        "perception": perception,
        "senses": senses,
        "languages": languages,
        "skills": skills,
        "str_mod": abilities["str"], "dex_mod": abilities["dex"], "con_mod": abilities["con"],
        "int_mod": abilities["int"], "wis_mod": abilities["wis"], "cha_mod": abilities["cha"],
        "ac": ac, "fortitude": fort, "reflex": reflex, "will": will, "hp": hp,
        "immunities": immunities, "weaknesses": weaknesses, "resistances": resistances,
        "speed": speed, "other_speeds": other_speeds, "speed_details": speed_details,
        "attacks": attacks,
        "abilities": special,
        "spells": primary_cast.get("spells") or spells,
        "spellcasting_entries": casting_entries,
        "spell_tradition": primary_cast.get("tradition") or "arcane",
        "spell_mode": primary_cast.get("mode") or "innate",
        "spell_dc": primary_cast.get("dc") or "",
        "spell_attack": "" if primary_cast.get("attack") is None else primary_cast.get("attack"),
        "spellcasting": "; ".join(c.get("label") or "" for c in casting_entries),
        "description": summary,
        "aon_url": url,
        "aon_source": source,
        "aon_source_page": source_page,
        "aon_imported_at": time.time(),
        "aon_parser_version": 3,
    }
    return {
        "title": name or title,
        "subtitle": " · ".join(x for x in [f"Creature {level}", f"{source} p. {source_page}" if source and source_page else source] if x),
        "summary": summary,
        "tags": ", ".join(traits),
        "payload": payload,
    }


def parse_aon_html(raw_html: str, *, url: str = "") -> dict[str, Any]:
    soup = BeautifulSoup(str(raw_html or ""), "html.parser")
    flat, _lined = _content_text(soup)
    return parse_aon_text(flat, title=_page_title(soup), summary=_meta_description(soup), url=url)


async def fetch_aon_creatures(urls: list[str]) -> list[AoNFetchResult]:
    if len(urls) > AON_MAX_LINKS:
        raise AoNImportError(f"Import at most {AON_MAX_LINKS} AoN links in one batch.")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        if not str(raw or "").strip():
            continue
        url = normalize_aon_url(raw)
        if url not in seen:
            normalized.append(url); seen.add(url)
    if not normalized:
        raise AoNImportError("Paste at least one Archives of Nethys creature link.")

    limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
    headers = {"User-Agent": AON_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    out: list[AoNFetchResult] = []
    async with httpx.AsyncClient(timeout=AON_TIMEOUT, follow_redirects=False, headers=headers, limits=limits) as client:
        for index, url in enumerate(normalized):
            if index:
                # Be polite to AoN during a bulk import; 25 links still complete quickly.
                await asyncio.sleep(0.12)
            try:
                current = url
                response = None
                # Follow only redirects that remain on the explicitly allowed AoN creature endpoints.
                # This avoids turning the server-side importer into a generic redirect-capable fetcher.
                for _hop in range(5):
                    response = await client.get(current)
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    location = str(response.headers.get("location") or "").strip()
                    if not location:
                        raise AoNImportError("Archives of Nethys returned an invalid redirect.")
                    current = normalize_aon_url(urljoin(current, location))
                else:
                    raise AoNImportError("Archives of Nethys redirected too many times.")
                assert response is not None
                response.raise_for_status()
                final = normalize_aon_url(str(response.url))
                if len(response.content) > AON_MAX_BYTES:
                    raise AoNImportError("The AoN page was unexpectedly large and was not imported.")
                encoding = response.encoding or "utf-8"
                raw_html = response.content.decode(encoding, errors="replace")
                parsed = parse_aon_html(raw_html, url=final)
                out.append(AoNFetchResult(url=final, parsed=parsed))
            except AoNImportError as exc:
                out.append(AoNFetchResult(url=url, error=str(exc)))
            except httpx.HTTPStatusError as exc:
                out.append(AoNFetchResult(url=url, error=f"Archives of Nethys returned HTTP {exc.response.status_code}."))
            except (httpx.HTTPError, UnicodeError) as exc:
                out.append(AoNFetchResult(url=url, error=f"Could not read Archives of Nethys: {exc}"))
            except Exception as exc:
                out.append(AoNFetchResult(url=url, error=f"Could not parse this AoN creature: {exc}"))
    return out
