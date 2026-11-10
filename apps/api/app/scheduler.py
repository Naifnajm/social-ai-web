"""Periodic task runner: ``uv run python -m app.scheduler`` (one instance). It enqueues due @periodic tasks."""
import logging
import time

from app.core import registry
from app.core.jobs import PERIODIC, enqueue

_logger = logging.getLogger("scheduler")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    registry.load_models()
    registry.load("tasks")
    last_run: dict[str, float] = {}
    _logger.info("periodic tasks: %s", ", ".join(sorted(PERIODIC)) or "none")
    while True:
        now = time.monotonic()
        for name, task in PERIODIC.items():
            if now - last_run.get(name, -1e9) >= task.seconds:
                last_run[name] = now
                try:
                    enqueue(task.func, queue="periodic")
                except Exception:
                    _logger.exception("could not enqueue %s", name)
        time.sleep(5)


if __name__ == "__main__":
    main()
