from __future__ import annotations

import argparse

from ..core.config import get_settings
from ..core.logging import configure_logging
from ..services.batch_analysis_service import run_batch_job


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one persisted image analysis job")
    parser.add_argument("job_id")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    configure_logging(get_settings().logging.level)
    run_batch_job(args.job_id, force=args.force)


if __name__ == "__main__":
    main()
