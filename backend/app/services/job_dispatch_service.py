import os
import subprocess
import sys

from fastapi import BackgroundTasks

from ..core.config import ROOT, get_settings


class JobDispatchError(RuntimeError):
    pass


def spawn_local_worker_process(job_id: str, force: bool = False) -> None:
    output_dir = ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"worker-{job_id}.log"
    command = [sys.executable, "-u", "-m", "backend.app.workers.local_worker", job_id]
    if force:
        command.append("--force")
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with log_path.open("ab") as log_handle:
            subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
                start_new_session=os.name != "nt",
            )
    except OSError as exc:
        raise JobDispatchError("เปิด AI worker process ไม่สำเร็จ") from exc


def dispatch_batch_job(background_tasks: BackgroundTasks, job_id: str, force: bool = False) -> None:
    """Dispatch analysis locally for development or to a dedicated Celery worker."""
    if get_settings().jobs.worker_mode == "celery":
        from ..workers.celery_app import celery_app

        try:
            celery_app.send_task("analysis.process_batch", args=[job_id], kwargs={"force": force})
        except Exception as exc:
            raise JobDispatchError("ส่งงานไปยัง AI worker ไม่สำเร็จ ตรวจสอบ Redis/Celery") from exc
        return
    if get_settings().jobs.worker_mode == "process":
        spawn_local_worker_process(job_id, force)
        return
    from .batch_analysis_service import run_batch_job

    background_tasks.add_task(run_batch_job, job_id, force)
