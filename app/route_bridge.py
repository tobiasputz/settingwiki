from __future__ import annotations

from types import ModuleType
from typing import Any


class _DynamicObject:
    """Attribute proxy for composition-root objects that tests/deployments may swap.

    The route split must preserve Seeker's long-standing ability to replace the
    active Settings object (the test suite does this heavily, and development
    reloaders can do the same). Keeping this proxy here avoids copying a stale
    object into every route module at import time.
    """

    __slots__ = ("_core", "_name")

    def __init__(self, core: ModuleType, name: str) -> None:
        object.__setattr__(self, "_core", core)
        object.__setattr__(self, "_name", name)

    def _target(self) -> Any:
        return getattr(object.__getattribute__(self, "_core"), object.__getattribute__(self, "_name"))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target(), name, value)

    def __repr__(self) -> str:
        return repr(self._target())

    def __str__(self) -> str:
        return str(self._target())

    def __fspath__(self) -> str:
        return self._target().__fspath__()


# These names are intentionally late-bound. They are common extension/testing
# seams in the historical composition root; forwarding them preserves behavior
# after route extraction instead of freezing the import-time implementation.
_LATE_CALLABLES = {
    "connect",
    "ensure_built",
    "_gallery_from_html",
    "discord_session_confirmation",
    "build_opener",
}


def _forward(core: ModuleType, name: str):
    def forwarded(*args: Any, **kwargs: Any) -> Any:
        return getattr(core, name)(*args, **kwargs)

    forwarded.__name__ = name
    forwarded.__qualname__ = name
    return forwarded


def bind_composition_root(namespace: dict[str, Any]) -> ModuleType:
    """Bind stable composition-root symbols used by extracted legacy routes.

    Seeker historically defined every endpoint in :mod:`app.main`. Version 10
    keeps every URL and handler contract intact while moving endpoint
    declarations into domain modules. The bridge is deliberately one-way:
    route modules consume composition-root services, while storage/domain
    modules never import routes. This enables incremental service extraction
    without a flag-day rewrite of mature handlers.
    """
    from . import main as core

    for name, value in vars(core).items():
        if name.startswith("__"):
            continue
        if name == "settings":
            namespace.setdefault(name, _DynamicObject(core, name))
        elif name in _LATE_CALLABLES and callable(value):
            namespace.setdefault(name, _forward(core, name))
        else:
            namespace.setdefault(name, value)
    return core
