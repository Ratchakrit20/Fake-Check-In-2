from ..services.batch_analysis_service import run_batch_job
from .celery_app import celery_app


@celery_app.task(bind=True, name="analysis.process_batch")
def process_batch(self, job_id: str, force: bool = False) -> None:
    """Run one persisted analysis job in a dedicated worker process."""
    if not run_batch_job(job_id, force=force):
        raise self.retry(countdown=20, max_retries=None)
