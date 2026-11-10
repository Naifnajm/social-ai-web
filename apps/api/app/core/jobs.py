"""Background jobs (RQ on Redis) and periodic tasks.

Run a function later in the worker (it gets a fresh DB session; pass ids, not objects)::

    from app.core.jobs import enqueue
    enqueue("app.modules.posts.tasks.publish_post", post_id)

Declare a periodic task in your module's ``tasks.py`` (picked up by the scheduler process)::

    from app.core.jobs import periodic

    @periodic(seconds=300)
    def sync_metrics():
        with session_scope() as db:
            ...

With ``SAI_JOBS_SYNC=true`` (tests) ``enqueue`` runs the function immediately in-process.
"""
import importlib
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal

_logger = logging.getLogger(__name__)


@dataclass
class PeriodicTask:
    name: str
    func: Callable
    seconds: int


PERIODIC: dict[str, PeriodicTask] = {}


def periodic(seconds: int):
    def decorator(func):
        name = f"{func.__module__}.{func.__name__}"
        PERIODIC[name] = PeriodicTask(name, func, seconds)
        return func
    return decorator


@contextmanager
def session_scope() -> Iterator[Session]:
    """A DB session for jobs: commits on success, rolls back on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _resolve(path: str) -> Callable:
    module, _, name = path.rpartition(".")
    return getattr(importlib.import_module(module), name)


def enqueue(func: str | Callable, *args, queue: str = "default", **kwargs):
    """Run ``func(*args, **kwargs)`` in the background worker (dotted path or function)."""
    target = _resolve(func) if isinstance(func, str) else func
    if settings.jobs_sync:
        return target(*args, **kwargs)
    from redis import Redis
    from rq import Queue
    return Queue(queue, connection=Redis.from_url(settings.redis_url)).enqueue(target, *args, **kwargs,
                                                                                job_timeout=1800)
