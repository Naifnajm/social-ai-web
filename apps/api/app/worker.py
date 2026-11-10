"""Background worker: ``uv run python -m app.worker`` (scale horizontally)."""
import logging

from redis import Redis
from rq import Queue, Worker

from app.core import registry
from app.core.config import settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    registry.load_models()
    registry.load("tasks")
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in ("default", "periodic", "media")]
    Worker(queues, connection=connection).work(with_scheduler=False)


if __name__ == "__main__":
    main()
