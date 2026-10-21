from types import SimpleNamespace

from fastapi import BackgroundTasks

from backend.app.services import job_dispatch_service


def test_process_mode_dispatches_worker_outside_api_process(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(job_dispatch_service, "ROOT", tmp_path)
    monkeypatch.setattr(
        job_dispatch_service,
        "get_settings",
        lambda: SimpleNamespace(jobs=SimpleNamespace(worker_mode="process")),
    )
    monkeypatch.setattr(job_dispatch_service.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))

    job_dispatch_service.dispatch_batch_job(BackgroundTasks(), "job-123", force=True)

    assert len(calls) == 1
    assert calls[0][0][0][-3:] == ["backend.app.workers.local_worker", "job-123", "--force"]
    assert calls[0][1]["cwd"] == tmp_path
    assert (tmp_path / "output" / "worker-job-123.log").exists()
