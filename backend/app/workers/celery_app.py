from celery import Celery

from ..core.config import get_settings

settings = get_settings()
celery_app = Celery("image_relation", broker=settings.jobs.broker_url, backend=settings.jobs.result_backend)
celery_app.conf.update(task_track_started=True, worker_prefetch_multiplier=1, task_acks_late=True)


@celery_app.task(name="analysis.healthcheck")
def healthcheck() -> dict:
    return {"status": "ok"}

