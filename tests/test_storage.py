from pathlib import Path
import zipfile
import pytest

from app.config import Settings
from app.storage import cleanup_legacy_import_artifacts, init_db, replace_project_from_zip, safe_extract_zip, storage_report


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


def test_import_does_not_leave_full_project_backup(tmp_path: Path):
    s=settings(tmp_path)
    (s.project_dir/'old.tex').write_text('old', encoding='utf-8')
    z=tmp_path/'new.zip'
    with zipfile.ZipFile(z,'w') as f:
        f.writestr('main.tex', r'\documentclass{book}\begin{document}New\end{document}')
    info=replace_project_from_zip(s,z)
    assert info['rollback_protected'] is True
    assert (s.project_dir/'main.tex').exists()
    assert not list(s.data_dir.glob('project-backup-*'))
    assert not list(s.data_dir.glob('import-*'))


def test_cleanup_removes_only_legacy_import_artifacts(tmp_path: Path):
    s=settings(tmp_path)
    (s.project_dir/'main.tex').write_text('active', encoding='utf-8')
    (s.data_dir/'project-backup-1').mkdir()
    (s.data_dir/'project-backup-1'/'main.tex').write_text('backup', encoding='utf-8')
    (s.data_dir/'upload-1.zip').write_bytes(b'junk')
    (s.uploads_dir/'keep.bin').write_bytes(b'keep')
    before=storage_report(s)
    assert before['legacy_import_bytes'] > 0
    result=cleanup_legacy_import_artifacts(s)
    assert result['freed_bytes'] > 0
    assert (s.project_dir/'main.tex').read_text() == 'active'
    assert (s.uploads_dir/'keep.bin').exists()
    assert not (s.data_dir/'project-backup-1').exists()
    assert not (s.data_dir/'upload-1.zip').exists()
