from pathlib import Path
import zipfile
import pytest

from app.config import Settings
from app.storage import init_db, replace_project_from_zip, safe_extract_zip


def settings(tmp_path: Path) -> Settings:
    p=tmp_path/'project';p.mkdir(); b=tmp_path/'build';b.mkdir(); h=tmp_path/'history';h.mkdir();u=tmp_path/'uploads';u.mkdir()
    return Settings(tmp_path,tmp_path,p,b,h,u,tmp_path/'db.sqlite','s','a',None,'pdflatex',20,False)


def test_rejects_zip_traversal(tmp_path: Path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f: f.writestr("../escape.tex", "bad")
    with pytest.raises(ValueError): safe_extract_zip(z, tmp_path / "extract")


def test_overleaf_zip_replaces_project(tmp_path: Path):
    s=settings(tmp_path);init_db(s)
    z=tmp_path/'project.zip'
    with zipfile.ZipFile(z,'w') as f:f.writestr('main.tex',r'\documentclass{book}\begin{document}Hello\end{document}')
    replace_project_from_zip(s,z)
    assert (s.project_dir/'main.tex').exists()
