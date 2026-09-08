from pathlib import Path

from app.config import Settings
from app.storage import init_db, save_codex_presentation
from app.latex import analyze_project, build_wiki, compile_pdf


def make_settings(tmp_path: Path) -> Settings:
    project = tmp_path / "project"; project.mkdir()
    build = tmp_path / "build"; build.mkdir()
    history = tmp_path / "history"; history.mkdir()
    uploads = tmp_path / "uploads"; uploads.mkdir()
    return Settings(
        root_dir=tmp_path, data_dir=tmp_path, project_dir=project, build_dir=build,
        history_dir=history, uploads_dir=uploads, db_path=tmp_path / "db.sqlite",
        session_secret="test", admin_password="test", player_password=None,
        latex_engine="pdflatex", latex_timeout=20, allow_shell_escape=False,
    )


def test_resolves_input_and_custom_macros(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(
        r"\documentclass{book}\newcommand{\npc}[2]{#1 #2}\title{Kiragon}\begin{document}\chapter{Ysrem}\input{town}\end{document}",
        encoding="utf-8",
    )
    (s.project_dir / "town.tex").write_text(
        r"\section{Moonbridge}\npc{Vanid}{Keeps the western gate.}\subsection{Market}Blue lanterns burn here.",
        encoding="utf-8",
    )
    analysis = analyze_project(s)
    assert analysis["main_file"] == "main.tex"
    assert any(x["name"] == "npc" and x["args"] == 2 for x in analysis["custom_macros"])
    wiki = build_wiki(s)
    titles = [x["title"] for x in wiki["pages"]]
    assert "Moonbridge" in titles
    page = next(x for x in wiki["pages"] if x["title"] == "Moonbridge")
    assert "Vanid" in page["plain_text"]


def test_unknown_macro_preserves_argument_text(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\section{Secret}\weirdformat{The Black Tower remains.}\end{document}",
        encoding="utf-8",
    )
    wiki = build_wiki(s)
    assert "The Black Tower remains" in wiki["pages"][0]["plain_text"]


def test_longtable_column_spec_never_leaks_into_prose(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(r'''\documentclass{book}
\begin{document}
\section{Calendar}
The year has unusual months.
\begin{longtable}{>{\centering\arraybackslash}p{1em} >{\raggedright\arraybackslash}p{3.5cm} >{\raggedright\arraybackslash}p{2.5cm} >{\raggedright\arraybackslash}p{5cm}}
\toprule
\# & Month Name & Gregorian & Festivals \\
\midrule
\endfirsthead
\toprule
\# & Month Name & Gregorian & Festivals \\
\midrule
\endhead
\bottomrule
\endlastfoot
1 & Dawncall & March & Founding Day \\
2 & Suncrest & April & Market Fair \\
\end{longtable}
\end{document}
''', encoding="utf-8")
    page = build_wiki(s)["pages"][0]
    assert '<table class="lore-table">' in page["html"]
    assert 'data-label="Month Name"' in page["html"]
    assert "longtable" not in page["plain_text"].lower()
    assert "raggedright" not in page["plain_text"].lower()
    assert "p3.5cm" not in page["plain_text"].lower()
    assert page["plain_text"].count("Month Name") == 1


def test_pon_becomes_single_entity_article_with_profile_and_portrait(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "Images" / "NPCs").mkdir(parents=True)
    (s.project_dir / "Images" / "NPCs" / "Tumerich_Tumadum.png").write_bytes(b"image")
    (s.project_dir / "main.tex").write_text(r'''\documentclass{book}
\newcommand{\pon}[1]{#1}
\begin{document}
\chapter{People}
\pon{Tumerich Tumadum}
\section{Profile}
\begin{multicols}{2}
\textbf{Ancestry:} Halfling\\
\textbf{Class:} Cleric\\
\textbf{Status:} Alive\\
\textbf{Position:} Officer of Finance
\end{multicols}
Intro text.
\begin{tikzpicture}[remember picture, overlay]
\node[inner sep=0pt, above] at (current page.south){\includegraphics[width=\paperwidth\relax]{Images/NPCs/Tumerich_Tumadum.png}};
\end{tikzpicture}
\newpage
\section{Biography}
Biography text.
\subsection{Fateful Meeting}
More biography.
\end{document}
''', encoding="utf-8")
    wiki = build_wiki(s)
    entity = next(p for p in wiki["pages"] if p["title"] == "Tumerich Tumadum")
    assert entity["level"] == "entity"
    assert '<dl class="lore-profile-grid">' in entity["html"]
    assert "lore-entity-portrait" in entity["html"]
    assert '<h2 id="biography">Biography' in entity["html"]
    assert '<h3 id="fateful-meeting">Fateful Meeting' in entity["html"]
    assert "tikzpicture" not in entity["plain_text"]
    assert "current page.south" not in entity["plain_text"]
    assert "paperwidth" not in entity["plain_text"]
    assert not any(p["title"] == "Biography" for p in wiki["pages"])


def test_loreforge_image_directive_controls_web_layout_without_leaking_comment(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "Images").mkdir()
    (s.project_dir / "Images" / "tower.png").write_bytes(b"image")
    (s.project_dir / "main.tex").write_text(r'''\documentclass{article}
\usepackage{graphicx}
\begin{document}
\section{Black Tower}
% loreforge-image: layout=right width=38 frame=ornate parallax=true caption="The Black Tower"
\includegraphics[width=.7\linewidth]{Images/tower.png}
The tower watches the valley.
\end{document}
''', encoding="utf-8")
    page = build_wiki(s)["pages"][0]
    assert "lore-image-layout-right" in page["html"]
    assert "lore-image-frame-ornate" in page["html"]
    assert "lore-image-parallax" in page["html"]
    assert "--image-width:38.0%" in page["html"]
    assert "The Black Tower" in page["html"]
    assert "loreforge-image" not in page["plain_text"]


def test_codex_presentation_is_embedded_in_pages_and_categories(tmp_path: Path):
    from app.storage import save_codex_presentation
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "Images").mkdir()
    (s.project_dir / "Images" / "chapter.png").write_bytes(b"image")
    (s.project_dir / "main.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n\\chapter{People}\n\\section{Vanid}\nA gatekeeper.\n\\end{document}\n",
        encoding="utf-8",
    )
    save_codex_presentation(s, "category", "people", {"toc_image": "project:Images/chapter.png"})
    save_codex_presentation(s, "page", "vanid", {"visibility": "teaser", "featured": True, "hero_style": "split"})
    wiki = build_wiki(s)
    page = next(x for x in wiki["pages"] if x["slug"] == "vanid")
    category = next(x for x in wiki["categories"] if x["slug"] == "people")
    assert page["presentation"]["visibility"] == "teaser"
    assert page["presentation"]["featured"] is True
    assert page["presentation"]["hero_style"] == "split"
    assert category["presentation"]["toc_image_url"].endswith("/project-asset/Images/chapter.png")


def test_scene_panel_and_free_art_direction_are_web_only(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "Images").mkdir()
    (s.project_dir / "Images" / "storm.jpg").write_bytes(b"image")
    (s.project_dir / "Images" / "sigil.png").write_bytes(b"image")
    (s.project_dir / "main.tex").write_text(r'''\documentclass{article}
\usepackage{graphicx}
\begin{document}
\section{The Storm Gate}
% loreforge-panel-start: image="Images/storm.jpg" opacity=0.42 x=72 y=38 tone=arcane min_height=360 parallax=true
The old gate hums whenever the moons align.
% loreforge-panel-end
% loreforge-image: layout=watermark width=44 opacity=0.22 blend=screen frame=none
\includegraphics[width=.4\linewidth]{Images/sigil.png}
Beyond it lies the drowned road.
\end{document}
''', encoding="utf-8")
    page = build_wiki(s)["pages"][0]
    assert "lore-scene-panel tone-arcane lore-scene-parallax" in page["html"]
    assert "--scene-opacity:0.420" in page["html"]
    assert "--scene-min-height:360px" in page["html"]
    assert "lore-image-layout-watermark" in page["html"]
    assert "lore-image-blend-screen" in page["html"]
    assert "loreforge-panel" not in page["plain_text"]
    assert "The old gate hums" in page["plain_text"]


def test_first_page_image_is_automatic_navigation_background_by_default(tmp_path: Path):
    from app.storage import set_setting
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "Images").mkdir()
    (s.project_dir / "Images" / "selen.png").write_bytes(b"image")
    (s.project_dir / "main.tex").write_text(r"""\documentclass{book}
\usepackage{graphicx}
\begin{document}
\chapter{Cities}
\section{Selenia}
\includegraphics[width=.8\linewidth]{Images/selen.png}
The silver city.
\end{document}
""", encoding="utf-8")
    wiki = build_wiki(s)
    page = next(x for x in wiki["pages"] if x["title"] == "Selenia")
    category = next(x for x in wiki["categories"] if x["title"] == "Cities")
    assert page["presentation"]["toc_image_url"] == ""
    assert page["presentation"]["auto_image_url"].endswith("/project-asset/Images/selen.png")
    assert page["presentation"]["display_toc_image_url"] == ""
    assert page["presentation"]["navigation_background_url"].endswith("/project-asset/Images/selen.png")
    assert page["presentation"]["navigation_art_is_auto"] is True
    assert category["presentation"]["display_toc_image_url"] == ""
    assert category["presentation"]["navigation_background_url"].endswith("/project-asset/Images/selen.png")

    set_setting(s, "auto_navigation_art", "0")
    wiki = build_wiki(s)
    page = next(x for x in wiki["pages"] if x["title"] == "Selenia")
    assert page["presentation"]["display_toc_image_url"] == ""
    assert page["presentation"]["navigation_background_url"] == ""
    assert page["presentation"]["navigation_art_is_auto"] is False

    save_codex_presentation(s, "page", page["slug"], {"toc_image": "project:Images/selen.png"})
    wiki = build_wiki(s)
    page = next(x for x in wiki["pages"] if x["title"] == "Selenia")
    assert page["presentation"]["display_toc_image_url"].endswith("/project-asset/Images/selen.png")
    assert page["presentation"]["navigation_background_url"].endswith("/project-asset/Images/selen.png")
    assert page["presentation"]["navigation_art_is_auto"] is False


def test_unique_codex_names_are_auto_linked_and_create_backlinks(tmp_path: Path):
    from app.storage import set_setting
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(r'''\documentclass{book}
\begin{document}
\chapter{People}
\section{Tumerich Tumadum}
A careful merchant.
\section{Corvina Dampierre}
Corvina trusts Tumerich Tumadum with the treasury.
\end{document}
''', encoding="utf-8")
    wiki = build_wiki(s)
    corvina = next(x for x in wiki["pages"] if x["title"] == "Corvina Dampierre")
    tumerich = next(x for x in wiki["pages"] if x["title"] == "Tumerich Tumadum")
    assert f'href="/wiki/{tumerich["slug"]}"' in corvina["html"]
    assert any(x["slug"] == corvina["slug"] for x in tumerich["backlinks"])

    set_setting(s, "auto_link_codex", "0")
    wiki_disabled = build_wiki(s)
    corvina_disabled = next(x for x in wiki_disabled["pages"] if x["title"] == "Corvina Dampierre")
    assert 'class="auto-wiki-link"' not in corvina_disabled["html"]


def test_build_doctor_recognizes_stale_latexmk_summary():
    from app.latex import _latex_failure_suggestions
    log = """Latexmk: Nothing to do for 'main.tex'.\nLatexmk: All targets () are up-to-date\nCollected error summary:\n  pdflatex: gave an error\n"""
    suggestions = _latex_failure_suggestions(log)
    assert any("cached" in x.lower() and "automatically" in x.lower() for x in suggestions)


def test_compile_pdf_self_heals_stale_latexmk_cache(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    import app.latex as latex_mod
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Recovered\end{document}", encoding="utf-8"
    )
    # Simulate the exact wrapper-only failure reported by Railway, then a
    # successful forced dependency rebuild after Loreforge clears cached state.
    calls = []
    def fake_which(name):
        return "/usr/bin/latexmk" if name == "latexmk" else f"/usr/bin/{name}"
    def fake_run(cmd, cwd, text, stdout, stderr, timeout, env):
        calls.append(list(cmd))
        if len(calls) == 1:
            return SimpleNamespace(returncode=12, stdout=(
                "Latexmk: Nothing to do for 'main.tex'.\n"
                "Latexmk: All targets () are up-to-date\n"
                "Collected error summary (may duplicate other messages):\n"
                "  pdflatex: gave an error\n"
            ))
        (Path(cwd) / "main.pdf").write_bytes(b"%PDF-1.4 recovered")
        return SimpleNamespace(returncode=0, stdout="Latexmk: forced rebuild complete\n")
    monkeypatch.setattr(latex_mod.shutil, "which", fake_which)
    monkeypatch.setattr(latex_mod.subprocess, "run", fake_run)
    result = compile_pdf(s)
    assert result.ok is True
    assert len(calls) == 2
    assert "-gg" in calls[1]
    assert "cached failed-build state" in result.recovery
    assert (s.build_dir / "campaign.pdf").exists()


def test_fontspec_project_auto_switches_from_pdflatex_to_xelatex(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    import app.latex as latex_mod
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(r'''\documentclass{book}
\usepackage{fontspec}
\setmainfont{TeX Gyre Adventor}
\begin{document}Hello\end{document}
''', encoding="utf-8")
    calls = []
    def fake_which(name):
        return f"/usr/bin/{name}"
    def fake_run(cmd, cwd, text, stdout, stderr, timeout, env):
        calls.append(list(cmd))
        (Path(cwd) / "main.pdf").write_bytes(b"%PDF-1.4 xelatex")
        return SimpleNamespace(returncode=0, stdout="XeLaTeX build complete\n")
    monkeypatch.setattr(latex_mod.shutil, "which", fake_which)
    monkeypatch.setattr(latex_mod.subprocess, "run", fake_run)
    result = compile_pdf(s)
    assert result.ok is True
    assert result.effective_engine == "xelatex"
    assert any("-xelatex" in call for call in calls)
    assert "fontspec" in result.recovery
    assert "switched" in result.recovery


def test_pf2e_custom_rule_macros_render_as_native_codex_cards(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(r'''\documentclass{book}
\newcommand{\actionOne}{ONE}
\newcommand{\actionTwo}{TWO}
\newcommand{\actionThree}{THREE}
\newcommand{\reaction}{REACTION}
\newcommand{\freeAction}{FREE}
\newcommand{\feat}[4]{#1 #2 #3 #4}
\newcommand{\action}[4]{#1 #2 #3 #4}
\newcommand{\itemtemplate}[4]{#1 #2 #3 #4}
\NewDocumentEnvironment{monster}{m m m m}{}{}
\newcommand{\monstersection}[1]{#1}
\newcommand{\monsterline}[2]{#1 #2}
\newcommand{\monsterabilityscores}[6]{#1 #2 #3 #4 #5 #6}
\newcommand{\monsterdefenses}[4]{#1 #2 #3 #4}
\newcommand{\monsterspeed}[1]{#1}
\newcommand{\monsterattack}[4]{#1 #2 #3 #4}
\newcommand{\monsterspellcasting}[4]{#1 #2 #3 #4}
\newcommand{\monsterability}[2]{#1 #2}
\begin{document}
\section{Rules}
\feat{Impossible Accountant}{7}{Rare, Skill}{You can \textbf{balance} a ledger while threatened. Use \actionOne to audit a foe.}
\action{Emergency Audit}{\reaction}{Concentrate}{When a creature lies, expose the discrepancy.}
\itemtemplate{Sunstone Ledger}{Item 9}{Magical, Invested}{The pages remember every debt.}
\begin{monster}{Ledger Wyrm}{6}{Rare, Large, Dragon}{Bestiary of Bad Accounting}
\monsterline{Perception}{+14; darkvision}
\monsterabilityscores{+5}{+2}{+4}{+1}{+3}{+0}
\monsterdefenses{23}{Fort +16, Ref +12, Will +15}{HP 105}{Resistance 5 fire}
\monsterspeed{30 feet, fly 50 feet}
\monstersection{Offense}
\monsterattack{Melee \actionOne jaws}{17}{reach 10 feet}{2d10+8 piercing}
\monsterspellcasting{Arcane Innate Spells}{DC 24}{3rd fear}{The wyrm cannot cast while balancing books.}
\monsterability{Compound Interest}{A target that owes the wyrm takes \textbf{extra damage}.}
\end{monster}
\end{document}
''', encoding="utf-8")
    page = build_wiki(s)["pages"][0]
    html = page["html"]
    assert 'class="pf2-rule-card pf2-feat"' in html
    assert 'class="pf2-rule-card pf2-action"' in html
    assert 'class="pf2-rule-card pf2-item"' in html
    assert 'class="pf2-statblock pf2-monster"' in html
    assert "Impossible Accountant" in html
    assert "balance" in html
    assert "Emergency Audit" in html
    assert "Ledger Wyrm" in html
    assert "Creature 6" in html
    assert "Compound Interest" in html
    assert "pf2-action-symbol" in html
    assert "monsterattack" not in page["plain_text"]
    assert "feat" not in page["plain_text"].lower() or "Feat 7" in page["plain_text"]


def test_legacy_image_macro_renders_responsive_image(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "Images").mkdir()
    (s.project_dir / "Images" / "relic.png").write_bytes(b"image")
    (s.project_dir / "main.tex").write_text(r'''\documentclass{article}
\newcommand{\image}[2]{#2}
\begin{document}
\section{Relic}
\image{0.45\textwidth}{Images/relic.png}
\end{document}
''', encoding="utf-8")
    page = build_wiki(s)["pages"][0]
    assert "lore-image-custom" in page["html"]
    assert "--image-width:45.0%" in page["html"]
    assert "/project-asset/Images/relic.png" in page["html"]


def test_chaptergroup_becomes_navigation_group_not_empty_page(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(r'''\documentclass{book}
\newcommand{\chaptergroup}[1]{#1}
\begin{document}
\chaptergroup{Player Options}
\section{Feats}
Useful rules live here.
\section{Equipment}
Useful items live here.
\end{document}
''', encoding="utf-8")
    wiki = build_wiki(s)
    assert [c["title"] for c in wiki["categories"]] == ["Player Options"]
    assert [p["title"] for p in wiki["pages"]] == ["Feats", "Equipment"]
    assert all(p["chapter"] == "Player Options" for p in wiki["pages"])
    assert not any(p["title"] == "Player Options" for p in wiki["pages"])


def test_engine_switch_clears_old_latexmk_dependency_state(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    import app.latex as latex_mod
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(r'''\documentclass{book}
\usepackage{fontspec}
\setmainfont{TeX Gyre Adventor}
\begin{document}Hello\end{document}
''', encoding="utf-8")
    stale = s.project_dir / "main.fdb_latexmk"
    stale.write_text("old pdflatex state", encoding="utf-8")
    calls = []
    monkeypatch.setattr(latex_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    def fake_run(cmd, cwd, text, stdout, stderr, timeout, env):
        calls.append(list(cmd))
        (Path(cwd) / "main.pdf").write_bytes(b"%PDF-1.4 xelatex")
        return SimpleNamespace(returncode=0, stdout="XeLaTeX build complete\n")
    monkeypatch.setattr(latex_mod.subprocess, "run", fake_run)
    result = compile_pdf(s)
    assert result.ok is True
    assert result.effective_engine == "xelatex"
    assert not stale.exists()
    assert "previous LaTeX engine" in result.recovery
    assert any("-xelatex" in call for call in calls)

def test_build_doctor_offers_safe_fixes_for_common_imported_source_errors(tmp_path: Path):
    from app.latex import _attach_quick_fixes
    s = make_settings(tmp_path); init_db(s)
    src = s.project_dir / "broken.tex"
    src.write_text(
        "\\subsubsection{Devotee Benefits} \\\\\n"
        "\\textbf{Edicts:} Endure.\n"
        "\\begin{multicols}\n"
        "\\action{Detonating Rune}{Focus Spell}{Arcane}{Rules}\n"
        "\\subsubection{Primary Shards}\n"
        "The council meets.\\The event is public.\n",
        encoding="utf-8",
    )
    errors = [
        {"path":"broken.tex","file":"broken.tex","line":2,"message":"LaTeX Error: There's no line here to end."},
        {"path":"broken.tex","file":"broken.tex","line":4,"message":"Missing number, treated as zero."},
        {"path":"broken.tex","file":"broken.tex","line":5,"message":"Undefined control sequence."},
        {"path":"broken.tex","file":"broken.tex","line":6,"message":"Undefined control sequence."},
    ]
    fixed = _attach_quick_fixes(errors, s.project_dir)
    assert fixed[0]["quick_fix"]["replacement"] == r"\subsubsection{Devotee Benefits}"
    assert fixed[1]["quick_fix"]["replacement"] == r"\begin{multicols}{2}"
    assert r"\subsubsection" in fixed[2]["quick_fix"]["replacement"]
    assert r"\The" not in fixed[3]["quick_fix"]["replacement"]

def test_compile_keeps_fresh_pdf_preview_when_xelatex_returns_errors(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    import app.latex as latex_mod
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(r'''\documentclass{book}
\usepackage{fontspec}
\begin{document}Broken but renderable\end{document}
''', encoding="utf-8")
    monkeypatch.setattr(latex_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    def fake_run(cmd, cwd, text, stdout, stderr, timeout, env):
        (Path(cwd) / "main.pdf").write_bytes(b"%PDF-1.4 partial")
        return SimpleNamespace(returncode=12, stdout="main.tex:3: Undefined control sequence.\n")
    monkeypatch.setattr(latex_mod.subprocess, "run", fake_run)
    result = compile_pdf(s)
    assert result.ok is False
    assert result.partial_pdf is True
    assert result.pdf_path == "/preview/pdf"
    assert (s.build_dir / "campaign.pdf").exists()

def test_build_doctor_can_consolidate_duplicate_geometry_declarations(tmp_path: Path):
    from app.latex import _attach_quick_fixes
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "main.tex").write_text(
        "\\documentclass{book}\n"
        "\\usepackage[a4paper,margin=0in]{geometry}\n"
        "\\usepackage{tcolorbox}\n"
        "\\usepackage[margin=1in]{geometry}\n"
        "\\begin{document}Hello\\end{document}\n",
        encoding="utf-8",
    )
    errors = [
        {"path":"main.tex","file":"main.tex","line":3,"message":"LaTeX Error: Option clash for package geometry."},
        {"path":"main.tex","file":"main.tex","line":5,"message":"LaTeX Error: Option clash for package geometry."},
    ]
    fixed = _attach_quick_fixes(errors, s.project_dir)
    fix = fixed[0].get("quick_fix")
    assert fix is not None
    assert len(fix["edits"]) == 2
    assert fix["edits"][0]["replacement"] == r"\usepackage{geometry}\geometry{a4paper,margin=1in}"
    assert fix["edits"][1]["replacement"].startswith("% Loreforge consolidated duplicate geometry declaration:")
    assert "quick_fix" not in fixed[1]

def test_batch_source_fixes_verify_then_apply_with_one_revision_per_file(tmp_path: Path, monkeypatch):
    import app.main as main_mod
    s = make_settings(tmp_path); init_db(s)
    monkeypatch.setattr(main_mod, "settings", s)
    src = s.project_dir / "broken.tex"
    src.write_text(
        "\\subsubsection{Devotee Benefits} \\\\\n"
        "\\begin{multicols}\n"
        "Text\n",
        encoding="utf-8",
    )
    fixes = [
        {"path":"broken.tex","line":1,"expected":r"\subsubsection{Devotee Benefits} \\","replacement":r"\subsubsection{Devotee Benefits}","label":"remove break"},
        {"path":"broken.tex","line":2,"expected":r"\begin{multicols}","replacement":r"\begin{multicols}{2}","label":"columns"},
    ]
    result = main_mod._apply_verified_source_fixes(fixes)
    assert result["edits"] == 2
    assert result["files"] == ["broken.tex"]
    text = src.read_text(encoding="utf-8")
    assert r"\subsubsection{Devotee Benefits}" in text
    assert r"\begin{multicols}{2}" in text
    assert len(list(s.history_dir.iterdir())) == 1

def test_extract_failure_excerpt_surfaces_classic_tex_error():
    from app.latex import _extract_failure_excerpt
    log = """Latexmk wrapper\nRunning xelatex\n(./main.tex\n! LaTeX Error: File `mystery.sty' not found.\n\nType X to quit.\nl.42 \\usepackage{mystery}\nEmergency stop.\n"""
    excerpt = _extract_failure_excerpt(log)
    assert "mystery.sty" in excerpt
    assert "l.42" in excerpt
    assert "Latexmk wrapper" not in excerpt


def test_extract_failure_excerpt_falls_back_to_log_tail():
    from app.latex import _extract_failure_excerpt
    log = "\n".join(f"opaque engine line {i}" for i in range(50))
    excerpt = _extract_failure_excerpt(log)
    assert "opaque engine line 49" in excerpt
    assert "opaque engine line 0" not in excerpt


def test_build_doctor_does_not_call_unrelated_xelatex_fatal_error_pdftex_fontspec():
    from app.latex import _latex_failure_suggestions
    log = """This is XeTeX, Version 3.141592653
(/usr/share/texlive/texmf-dist/tex/latex/fontspec/fontspec.sty)
Some package output
! LaTeX Error: Something entirely unrelated broke.
Fatal error occurred, no output PDF file produced.
"""
    suggestions = _latex_failure_suggestions(log, "xelatex")
    joined = "\n".join(suggestions).lower()
    assert "cannot run under pdflatex" not in joined
    assert "font is unavailable" not in joined
    assert "requested font" not in joined


def test_build_doctor_reports_observed_engine_mismatch():
    from app.latex import _latex_failure_suggestions
    log = """Running 'pdflatex main.tex'
This is pdfTeX, Version 3.141592653
! Fatal Package fontspec Error: The fontspec package requires either XeTeX or LuaTeX.
"""
    suggestions = _latex_failure_suggestions(log, "xelatex")
    assert any("selected xelatex" in x.lower() and "pdftex actually ran" in x.lower() for x in suggestions)


def test_build_doctor_only_reports_missing_font_when_log_names_one():
    from app.latex import _latex_failure_suggestions
    log = """This is XeTeX, Version 3.141592653
Package fontspec Error: The font \"Imaginary Rune Font\" cannot be found.
"""
    suggestions = _latex_failure_suggestions(log, "xelatex")
    assert any("Imaginary Rune Font" in x for x in suggestions)


def test_xelatex_xdv_stage_is_converted_separately_after_outer_failure(tmp_path: Path, monkeypatch):
    """A large XeLaTeX book may finish XDV generation before latexmk times out.

    Loreforge should finish xdvipdfmx as a separate stage instead of reporting
    the successful 300+ page XeLaTeX transcript as an unknown compile failure.
    """
    from types import SimpleNamespace
    import app.latex as latex_mod
    from dataclasses import replace

    s = make_settings(tmp_path); init_db(s)
    s = replace(s, latex_engine="auto", latex_timeout=20)
    (s.project_dir / "main.tex").write_text(r'''\documentclass{book}
\usepackage{fontspec}
\setmainfont{TeX Gyre Adventor}
\begin{document}A very long book.\end{document}
''', encoding="utf-8")

    calls = []
    def fake_which(name):
        if name in {"latexmk", "xelatex", "xdvipdfmx"}:
            return f"/usr/bin/{name}"
        return None

    def fake_run(cmd, cwd, text, stdout, stderr, timeout, env):
        calls.append((list(cmd), timeout))
        cwd = Path(cwd)
        if "latexmk" in Path(cmd[0]).name:
            (cwd / "main.xdv").write_bytes(b"fresh xdv")
            return SimpleNamespace(returncode=12, stdout=(
                "Latexmk: applying rule 'xelatex'...\n"
                "Output written on main.xdv (347 pages, 5929080 bytes).\n"
                "Loreforge stopped this build stage after 20s.\n"
            ))
        if "xdvipdfmx" in Path(cmd[0]).name:
            (cwd / "main.pdf").write_bytes(b"%PDF-1.4 recovered from xdv")
            return SimpleNamespace(returncode=0, stdout="main.xdv -> main.pdf\n347 pages written\n")
        return SimpleNamespace(returncode=1, stdout="unexpected")

    monkeypatch.setattr(latex_mod.shutil, "which", fake_which)
    monkeypatch.setattr(latex_mod.subprocess, "run", fake_run)
    result = compile_pdf(s)
    assert result.ok is True
    assert result.effective_engine == "xelatex"
    assert any("xdvipdfmx" in Path(call[0][0]).name for call in calls)
    assert "XDV-to-PDF conversion" in result.recovery
    assert (s.build_dir / "campaign.pdf").exists()


def test_auto_xelatex_does_not_purge_aux_state_on_every_compile(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    import app.latex as latex_mod
    from dataclasses import replace

    s = make_settings(tmp_path); init_db(s)
    s = replace(s, latex_engine="auto")
    (s.project_dir / "main.tex").write_text(r'''\documentclass{article}
\usepackage{fontspec}
\begin{document}Hello\end{document}
''', encoding="utf-8")

    def fake_which(name):
        return f"/usr/bin/{name}"
    def fake_run(cmd, cwd, text, stdout, stderr, timeout, env):
        (Path(cwd) / "main.pdf").write_bytes(b"%PDF-1.4 ok")
        return SimpleNamespace(returncode=0, stdout="Latexmk: All targets are up-to-date\n")

    monkeypatch.setattr(latex_mod.shutil, "which", fake_which)
    monkeypatch.setattr(latex_mod.subprocess, "run", fake_run)

    first = compile_pdf(s)
    # Put an aux file back after the first build. The second AUTO -> xelatex
    # compile must preserve it rather than treating auto-selection as a switch.
    aux = s.project_dir / "main.aux"
    aux.write_text("keep me", encoding="utf-8")
    second = compile_pdf(s)
    assert first.ok and second.ok
    assert aux.exists()
    assert "previous LaTeX engine" not in second.recovery


def test_failure_excerpt_prefers_pipeline_timeout_over_clean_engine_tail():
    from app.latex import _extract_failure_excerpt
    log = (
        "Output written on main.xdv (347 pages, 5929080 bytes).\n"
        "Loreforge stopped this build stage after 60s.\n"
        "[TeX engine log]\n"
        "Package rerunfilecheck Info: File `main.out' has not changed.\n"
        "Output written on main.xdv (347 pages, 5929080 bytes).\n"
    )
    excerpt = _extract_failure_excerpt(log)
    assert "stopped this build stage after 60s" in excerpt


def test_automatic_navigation_background_skips_pf2e_action_symbol_images(tmp_path: Path):
    s = make_settings(tmp_path); init_db(s)
    (s.project_dir / "Images" / "Symbols").mkdir(parents=True)
    (s.project_dir / "Images" / "NPCs").mkdir(parents=True)
    (s.project_dir / "Images" / "Symbols" / "oneaction.png").write_bytes(b"icon")
    (s.project_dir / "Images" / "NPCs" / "hero.png").write_bytes(b"portrait")
    (s.project_dir / "main.tex").write_text(r"""\documentclass{book}
\usepackage{graphicx}
\begin{document}
\chapter{People}
\section{Hero}
\actionOne Attack quickly.
\includegraphics[width=.6\linewidth]{Images/NPCs/hero.png}
\end{document}
""", encoding="utf-8")
    page = next(x for x in build_wiki(s)["pages"] if x["title"] == "Hero")
    assert page["presentation"]["navigation_background_url"].endswith("/project-asset/Images/NPCs/hero.png")
