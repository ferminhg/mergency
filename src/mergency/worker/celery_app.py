from celery import Celery

celery_app = Celery(
    "mergency",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
    include=["mergency.worker.classify_activity_event"],
)
