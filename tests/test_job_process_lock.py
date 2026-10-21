from uuid import uuid4

from backend.app.services.job_process_lock import job_process_lock


def test_job_lock_rejects_a_second_local_worker():
    job_id = str(uuid4())
    with job_process_lock(job_id) as first:
        assert first
        with job_process_lock(job_id) as second:
            assert not second
