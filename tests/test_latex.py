from pathlib import Path

from app.config import Settings
from app.storage import init_db
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
    assert "<h2>Biography</h2>" in entity["html"]
    assert "<h3>Fateful Meeting</h3>" in entity["html"]
    assert "tikzpicture" not in entity["plain_text"]
    assert "current page.south" not in entity["plain_text"]
    assert "paperwidth" not in entity["plain_text"]
    assert not any(p["title"] == "Biography" for p in wiki["pages"])
