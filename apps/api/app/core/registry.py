"""Feature modules are discovered automatically: every package in ``app/modules`` may provide

* ``models.py``  — SQLAlchemy models (imported so the tables exist),
* ``router.py``  — a FastAPI ``router`` (mounted under /api),
* ``public.py``  — a FastAPI ``router`` mounted at the root (webhooks, short links, public media…),
* ``tasks.py``   — background jobs and ``@periodic`` tasks.

Adding a feature never requires editing a shared file.
"""
import importlib
import pkgutil

import app.modules as modules_pkg


def module_names() -> list[str]:
    return sorted(name for _finder, name, is_pkg in pkgutil.iter_modules(modules_pkg.__path__) if is_pkg)


def _import_optional(path: str):
    try:
        return importlib.import_module(path)
    except ModuleNotFoundError as exc:
        if exc.name == path:
            return None
        raise


def load(kind: str) -> list:
    loaded = []
    for name in module_names():
        module = _import_optional(f"app.modules.{name}.{kind}")
        if module is not None:
            loaded.append(module)
    return loaded


def load_models() -> None:
    import app.core.models  # noqa: F401
    load("models")
