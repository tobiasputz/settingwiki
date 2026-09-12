from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"


def _template_buttons(text: str):
    return list(re.finditer(r"<button\b([^>]*)>(.*?)</button>", text, re.S | re.I))


def _inside_open_form(text: str, offset: int) -> bool:
    before = text[:offset]
    return before.rfind("<form") > before.rfind("</form>")


def test_every_static_button_has_a_submit_semantic_or_click_binding():
    """Prevent visible controls from silently shipping without any behavior.

    This is intentionally source-level rather than browser-framework dependent,
    so it runs in CI and catches the common regression where markup is added but
    its handler never is.
    """
    js = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in STATIC.glob("*.js"))
    failures = []
    for template in TEMPLATES.glob("*.html"):
        text = template.read_text(encoding="utf-8", errors="ignore")
        inline = "\n".join(re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", text, re.S | re.I))
        corpus = js + "\n" + inline
        for match in _template_buttons(text):
            attrs = match.group(1)
            label = " ".join(re.sub(r"<.*?>", " ", match.group(2)).split())[:80]
            if "onclick=" in attrs.lower():
                continue
            if re.search(r'type\s*=\s*["\'](?:submit|reset)["\']', attrs, re.I):
                continue
            # HTML buttons inside a form submit by default unless explicitly
            # type=button, so those are functional without JS.
            if _inside_open_form(text, match.start()) and not re.search(r'type\s*=\s*["\']button["\']', attrs, re.I):
                continue

            ids = re.findall(r'id\s*=\s*["\']([^"\']+)', attrs, re.I)
            datas = re.findall(r'(data-[\w-]+)', attrs, re.I)
            classes = []
            cm = re.search(r'class\s*=\s*["\']([^"\']+)', attrs, re.I)
            if cm:
                classes = cm.group(1).split()
            bound = False
            for id_value in ids:
                if f"#{id_value}" in corpus or f"getElementById('{id_value}')" in corpus or f'getElementById("{id_value}")' in corpus:
                    bound = True
            for data_name in datas:
                raw = data_name[5:]
                parts = raw.split("-")
                camel = parts[0] + "".join(x.title() for x in parts[1:])
                if f"[{data_name}" in corpus or f"dataset.{camel}" in corpus:
                    bound = True
            for cls in classes:
                if f".{cls}" in corpus:
                    bound = True
            if not bound:
                failures.append(f"{template.name}: {label or '<unlabelled>'} ({attrs.strip()})")
    assert not failures, "Visible buttons without a submit action or JS binding:\n" + "\n".join(failures)


def test_literal_internal_links_point_to_registered_routes():
    routes = set()
    for source in (ROOT / "app").glob("*.py"):
        text = source.read_text(encoding="utf-8", errors="ignore")
        routes.update(re.findall(r'@app\.(?:get|post|put|delete|patch)\(["\']([^"\']+)', text))
    missing = []
    for template in TEMPLATES.glob("*.html"):
        text = template.read_text(encoding="utf-8", errors="ignore")
        for href in re.findall(r'href=["\']([^"\']+)["\']', text):
            if "{{" in href or "{%" in href or href.startswith(("#", "http", "mailto:", "tel:", "javascript:")):
                continue
            path = href.split("#", 1)[0].split("?", 1)[0] or "/"
            if path.startswith(("/static/", "/uploads/", "/project-asset/")):
                continue
            if path not in routes:
                missing.append(f"{template.name}: {href}")
    assert not missing, "Literal UI links with no registered route:\n" + "\n".join(missing)


def _values(text: str, attr: str) -> set[str]:
    return set(re.findall(rf'{re.escape(attr)}=["\']([^"\']+)', text))


def test_core_tab_buttons_always_have_matching_panes():
    pairs = [
        ("living.html", "data-living-tab", "data-living-pane"),
        ("living_admin.html", "data-la-tab", "data-la-pane"),
        ("v7_player.html", "data-player-tab", "data-player-pane"),
        ("v7_hub.html", "data-v7-tab", "data-v7-pane"),
        ("v8_workspace.html", "data-v8-tab", "data-v8-pane"),
    ]
    for filename, tab_attr, pane_attr in pairs:
        text = (TEMPLATES / filename).read_text(encoding="utf-8")
        assert _values(text, tab_attr) == _values(text, pane_attr), filename
    cc = (TEMPLATES / "campaign_admin.html").read_text(encoding="utf-8")
    tabs = _values(cc, "data-cc-tab")
    panes = set(re.findall(r'id=["\']cc-([^"\']+)', cc))
    assert tabs <= panes


def test_journal_and_relationship_navigation_has_shared_fallback():
    core = (STATIC / "ui-core.js").read_text(encoding="utf-8")
    for token in ("data-living-tab", "data-player-tab", "data-cc-tab", "data-la-tab"):
        assert token in core
    living = (TEMPLATES / "living.html").read_text(encoding="utf-8")
    player = (TEMPLATES / "v7_player.html").read_text(encoding="utf-8")
    worldcraft = (TEMPLATES / "campaign_admin.html").read_text(encoding="utf-8")
    state = (TEMPLATES / "living_admin.html").read_text(encoding="utf-8")
    assert 'data-living-tab="journal"' in living and 'data-living-pane="journal"' in living
    assert 'data-player-tab="journal"' in player and 'data-player-pane="journal"' in player
    assert 'data-cc-tab="relationships"' in worldcraft and 'id="cc-relationships"' in worldcraft
    assert 'data-la-tab="relationships"' in state and 'data-la-pane="relationships"' in state


def test_studio_auxiliary_buttons_are_wired():
    html = (TEMPLATES / "admin.html").read_text(encoding="utf-8")
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    for control, handler in (
        ("menuBtn", "showStudioMenu"),
        ("addMapLayerBtn", "showMapLayerUpload"),
        ("addFogRegionBtn", "showQuickFogRegion"),
    ):
        assert f'id="{control}"' in html
        assert f"#{control}" in js and handler in js
    assert "renderMapAuxiliary" in js


def test_ui_core_is_shipped_and_cached():
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    cc = (TEMPLATES / "campaign_admin.html").read_text(encoding="utf-8")
    la = (TEMPLATES / "living_admin.html").read_text(encoding="utf-8")
    player = (TEMPLATES / "v7_player.html").read_text(encoding="utf-8")
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    for text in (base, cc, la, player):
        assert "/static/ui-core.js?v=10000" in text
    assert "/static/ui-core.js?v=10000" in sw
    assert "seeker-static-v10000" in sw


def test_generated_data_action_buttons_have_a_handler():
    """Catch JS-rendered buttons which look actionable but have no matching handler.

    Generated plain submit buttons are intentionally ignored.  For buttons with
    data-* action metadata, at least one data attribute must be consumed by a
    selector or dataset access elsewhere in the same module.
    """
    failures = []
    for source in STATIC.glob("*.js"):
        text = source.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"<button\b([^>]*)>", text, re.S | re.I):
            attrs = match.group(1)
            data_attrs = re.findall(r"\b(data-[a-zA-Z0-9_-]+)", attrs)
            if not data_attrs:
                continue
            rest = text[:match.start()] + text[match.end():]
            handled = False
            for data_name in data_attrs:
                raw = data_name[5:]
                parts = raw.split("-")
                camel = parts[0] + "".join(x.title() for x in parts[1:])
                if (
                    f"[{data_name}" in rest
                    or f"dataset.{camel}" in rest
                    or f'dataset["{raw}"]' in rest
                    or f"dataset['{raw}']" in rest
                ):
                    handled = True
                    break
            if not handled:
                snippet = " ".join(match.group(0).split())[:160]
                failures.append(f"{source.name}: {snippet}")
    assert not failures, "Generated action buttons without a matching JS handler:\n" + "\n".join(failures)


def test_session_workflow_stages_are_not_fake_buttons():
    text = (STATIC / "v8.js").read_text(encoding="utf-8")
    assert 'data-stage=' not in text
    assert 'class="v8-stage' in text


def test_generated_id_buttons_are_referenced_by_their_module():
    failures = []
    for source in STATIC.glob("*.js"):
        text = source.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"<button\b([^>]*)>", text, re.S | re.I):
            attrs = match.group(1)
            id_match = re.search(r'\bid=["\']([^"\']+)', attrs, re.I)
            if not id_match or "${" in id_match.group(1):
                continue
            ident = id_match.group(1)
            rest = text[:match.start()] + text[match.end():]
            if not (
                f"#{ident}" in rest
                or f"getElementById('{ident}')" in rest
                or f'getElementById("{ident}")' in rest
            ):
                failures.append(f"{source.name}: #{ident}")
    assert not failures, "Generated id buttons not referenced by their module:\n" + "\n".join(failures)


def test_shared_modal_styles_live_in_player_stylesheet():
    css=(STATIC/'wiki.css').read_text(encoding='utf-8')
    assert '.modal-backdrop{position:fixed' in css
    assert '.modal{position:relative' in css
    assert 'body.modal-open{overflow:hidden!important}' in css
    assert '@media(max-width:640px)' in css and 'seekerModalSheet' in css
    assert '.toast-stack{position:fixed' in css


def test_generic_modal_pages_use_overlay_and_accessible_dialog_markup():
    for filename, ident in (
        ('living.html','livingModal'),('session.html','livingModal'),('living_admin.html','laModal'),
        ('gm_session.html','gmSessionModal'),('gm_prep.html','gmPrepModal'),('campaign_admin.html','ccModal'),
    ):
        text=(TEMPLATES/filename).read_text(encoding='utf-8')
        assert f'id="{ident}"' in text, filename
        assert 'modal-backdrop hidden' in text, filename
        assert 'aria-hidden="true"' in text, filename
        assert 'role="dialog"' in text and 'aria-modal="true"' in text, filename


def test_living_dialog_controller_cannot_fall_into_document_flow():
    js=(STATIC/'living.js').read_text(encoding='utf-8')
    for token in (
        "document.body.classList.add('modal-open')",
        "document.body.classList.remove('modal-open')",
        "shell.setAttribute('aria-hidden','false')",
        "e.target===shell",
        "e.key==='Escape'",
    ):
        assert token in js


def test_shared_modal_controllers_lock_background_scroll():
    modules={
        'campaign-admin.js':'ccModal',
        'gm-prep.js':'gmPrepModal',
        'gm-session.js':'gmSessionModal',
        'living-admin.js':'laModal',
    }
    for filename, ident in modules.items():
        js=(STATIC/filename).read_text(encoding='utf-8')
        assert "classList.add('modal-open')" in js, filename
        assert "classList.remove('modal-open')" in js, filename
        assert "e.key==='Escape'" in js, filename
        assert ident in js, filename
