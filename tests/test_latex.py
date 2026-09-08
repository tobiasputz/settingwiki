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
