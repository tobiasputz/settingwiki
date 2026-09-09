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


def test_codex_presentation_roundtrip_and_validation(tmp_path: Path):
    from app.storage import get_codex_presentation, save_codex_presentation
    s=settings(tmp_path);init_db(s)
    saved=save_codex_presentation(s,'page','black-tower',{
        'toc_image':'project:Images/tower.png','visibility':'nonsense','hero_style':'split',
        'article_layout':'cinematic','background_opacity':9,'background_x':-5,'background_y':120,'featured':True,
    })
    assert saved['visibility']=='public'
    assert saved['background_opacity']==0.8
    assert saved['background_x']==0
    assert saved['background_y']==100
    loaded=get_codex_presentation(s,'page','black-tower')
    assert loaded['toc_image']=='project:Images/tower.png'
    assert loaded['hero_style']=='split'
    assert loaded['article_layout']=='cinematic'
    assert loaded['featured'] is True


def test_player_invitation_roundtrip_revoke_and_rotate(tmp_path: Path):
    from app.storage import (
        create_player_invite, register_player_device, resolve_player_invite, revoke_player_invite,
        rotate_player_invite, validate_player_invite_session,
    )
    s=settings(tmp_path);init_db(s)
    invite=create_player_invite(s,'Sarah')
    assert invite['active'] is True
    assert invite['invite_path'].startswith('/invite/lf1.')
    accepted=resolve_player_invite(s,invite['token'])
    assert accepted and accepted['label']=='Sarah'
    assert accepted['use_count']==1
    device=register_player_device(s,accepted['id'],accepted['access_version'])
    assert validate_player_invite_session(s,accepted['id'],accepted['access_version'],device)
    revoke_player_invite(s,accepted['id'])
    assert resolve_player_invite(s,invite['token']) is None
    assert validate_player_invite_session(s,accepted['id'],accepted['access_version'],device) is None
    rotated=rotate_player_invite(s,accepted['id'])
    assert rotated['active'] is True
    assert rotated['token'] != invite['token']
    assert resolve_player_invite(s,invite['token']) is None
    assert resolve_player_invite(s,rotated['token']) is not None


def test_player_invitation_expiry_is_enforced(tmp_path: Path):
    from app.storage import create_player_invite, resolve_player_invite
    import time
    s=settings(tmp_path);init_db(s)
    invite=create_player_invite(s,'Temporary player',time.time()+0.02)
    assert resolve_player_invite(s,invite['token'],record_use=False) is not None
    time.sleep(0.03)
    assert resolve_player_invite(s,invite['token'],record_use=False) is None


def test_player_invitation_device_limit_and_reset(tmp_path: Path):
    from app.storage import (
        create_player_invite, get_player_invite, register_player_device,
        reset_player_invite_devices, validate_player_invite_session,
    )
    s=settings(tmp_path);init_db(s)
    invite=create_player_invite(s,'One-browser player',max_devices=1)
    first=register_player_device(s,invite['id'],invite['access_version'],user_agent='Phone A')
    assert validate_player_invite_session(s,invite['id'],invite['access_version'],first)
    # Reopening in the same browser reuses its slot.
    assert register_player_device(s,invite['id'],invite['access_version'],existing_device_id=first)==first
    with pytest.raises(ValueError, match='device limit'):
        register_player_device(s,invite['id'],invite['access_version'],user_agent='Phone B')
    info=get_player_invite(s,invite['id'])
    assert info['device_count']==1 and info['max_devices']==1
    reset_player_invite_devices(s,invite['id'])
    assert validate_player_invite_session(s,invite['id'],invite['access_version'],first) is None
    second=register_player_device(s,invite['id'],invite['access_version'],user_agent='Phone B')
    assert second != first
