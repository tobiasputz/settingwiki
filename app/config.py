from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    project_dir: Path
    build_dir: Path
    history_dir: Path
    uploads_dir: Path
    db_path: Path
    session_secret: str
    admin_password: str
    player_password: str | None
    latex_engine: str
    latex_timeout: int
    allow_shell_escape: bool


def _persistent_secret(path: Path, env_name: str, *, token_bytes: int = 32) -> str:
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(token_bytes)
    path.write_text(value, encoding="utf-8")
    return value


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    data = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else root / ".data")).resolve()
    data.mkdir(parents=True, exist_ok=True)
    project = data / "project"
    build = data / "build"
    history = data / "history"
    uploads = data / "uploads"
    for p in (project, build, history, uploads):
        p.mkdir(parents=True, exist_ok=True)

    password_file = data / ".admin_password"
    admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    generated = False
    if not admin_password:
        if password_file.exists():
            admin_password = password_file.read_text(encoding="utf-8").strip()
        else:
            admin_password = secrets.token_urlsafe(10)
            password_file.write_text(admin_password, encoding="utf-8")
            generated = True
    if generated:
        print("\n" + "=" * 72)
        print("LOREFORGE FIRST-RUN ADMIN PASSWORD:", admin_password)
        print("Set ADMIN_PASSWORD in Railway Variables to choose your own password.")
        print("=" * 72 + "\n", flush=True)

    return Settings(
        root_dir=root,
        data_dir=data,
        project_dir=project,
        build_dir=build,
        history_dir=history,
        uploads_dir=uploads,
        db_path=data / "loreforge.db",
        session_secret=_persistent_secret(data / ".session_secret", "SESSION_SECRET"),
        admin_password=admin_password,
        player_password=os.getenv("PLAYER_PASSWORD", "").strip() or None,
        latex_engine=os.getenv("LATEX_ENGINE", "pdflatex").strip().lower(),
        latex_timeout=max(10, int(os.getenv("LATEX_TIMEOUT", "60"))),
        allow_shell_escape=os.getenv("LATEX_ALLOW_SHELL_ESCAPE", "0").lower() in {"1", "true", "yes"},
    )
