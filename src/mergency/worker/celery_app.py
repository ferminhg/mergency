import os

from celery import Celery

_REDIS_URL = os.environ.get("MERGENCY_REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "mergency",
    broker=_REDIS_URL,
    backend=_REDIS_URL,
    include=[
        "mergency.worker.classify_activity_event",
        "mergency.worker.evaluate_pr_budget",
        "mergency.worker.report_incident",
    ],
)
