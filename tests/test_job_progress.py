from types import SimpleNamespace

from backend.app.api.routes.jobs import _job_response


def make_job(*, processed: int, total: int = 5000) -> SimpleNamespace:
    return SimpleNamespace(
        id="job-1",
        status="VERIFYING",
        total=total,
        processed=processed,
        error=None,
        started_at=None,
        completed_at=None,
        duration_seconds=None,
    )


def test_job_response_reconciles_progress_with_completed_checkpoints() -> None:
    response = _job_response(make_job(processed=2332), completed_items=2643)

    assert response["processed"] == 2643


def test_job_response_never_lowers_counter_and_caps_at_total() -> None:
    assert _job_response(make_job(processed=2600), completed_items=2400)["processed"] == 2600
    assert _job_response(make_job(processed=5100), completed_items=5000)["processed"] == 5000
