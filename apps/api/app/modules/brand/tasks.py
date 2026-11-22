"""Brand kits: forget design-system uploads nobody committed (they wait an hour, see router_import.py)."""
from app.core.jobs import periodic, session_scope


@periodic(seconds=3600)
def drop_expired_imports():
    from . import router_import
    with session_scope() as db:
        router_import._cleanup(db)
