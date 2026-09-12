from __future__ import annotations

"""Ordered Seeker storage bootstrap.

Historically each release initialized its own tables directly from ``main.py``.
Keeping the same order behind one registry preserves every existing schema while
making upgrades auditable and giving future migrations one home.
"""

import time

from .config import Settings
from .storage import connect, init_db, seed_project
from .features import init_feature_db
from .scheduling import init_schedule_db
from .v5 import init_v5_db
from .v51 import init_v51_db
from .v6 import init_v6_db
from .v7 import init_v7_db
from .v8 import init_v8_db
from .homebrew_global import init_global_homebrew
from .v9 import init_v9_db
from .v10 import init_v10_db

INITIALIZERS = (
    ("core", "Legacy/core storage", init_db),
    ("features", "Campaign feature storage", init_feature_db),
    ("scheduling", "Scheduling storage", init_schedule_db),
    ("5", "Seeker v5 storage", init_v5_db),
    ("5.1", "Seeker v5.1 storage", init_v51_db),
    ("6", "Seeker v6 storage", init_v6_db),
    ("7", "Seeker v7 storage", init_v7_db),
    ("8", "Seeker v8 workspace storage", init_v8_db),
    ("homebrew-global", "Shared Homebrew library", init_global_homebrew),
    ("9", "Seeker v9 storage", init_v9_db),
)


def initialize_storage(settings: Settings) -> None:
    # Preserve the exact proven initialization order from 9.0.5.
    for _, _, initializer in INITIALIZERS:
        initializer(settings)
    init_v10_db(settings)
    now = time.time()
    with connect(settings) as conn:
        for version, description, _ in INITIALIZERS:
            conn.execute(
                "INSERT OR IGNORE INTO seeker_schema_migrations(version,description,applied_at) VALUES(?,?,?)",
                (version, description, now),
            )
    seed_project(settings)
