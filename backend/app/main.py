import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .api.router import api_router
from .core.config import ROOT, get_settings
from .core.exceptions import ApplicationError
from .core.logging import configure_logging
from .core.runtime import detect_hardware
from .db.models import AnalysisJob
from .db.session import SessionFactory, init_database
from .services.batch_analysis_service import run_batch_job

settings = get_settings()
configure_logging(settings.logging.level)
hardware = detect_hardware(
    settings.performance.cpu_workers,
    settings.performance.opencv_threads,
    settings.embedding.batch_size,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.getLogger(__name__).info(
        "runtime profile: device=%s vram=%.2fGB cpu=%d pair_workers=%d opencv_threads=%d embedding_batch=%d",
        hardware.device,
        hardware.vram_gb,
        hardware.logical_cpus,
        hardware.pair_workers,
        hardware.opencv_threads,
        hardware.embedding_batch_size,
    )
    Path(settings.storage.root).mkdir(parents=True, exist_ok=True)
    await init_database()
    async with SessionFactory() as session:
        interrupted = list(
            await session.scalars(
                select(AnalysisJob).where(AnalysisJob.status.not_in(["COMPLETED", "FAILED"]))
            )
        )
    recovery_tasks = [asyncio.create_task(asyncio.to_thread(run_batch_job, job.id)) for job in interrupted]
    yield
    for task in recovery_tasks:
        task.cancel()


app = FastAPI(title=settings.app.name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix=settings.app.api_prefix)


@app.exception_handler(ApplicationError)
async def application_error(_: Request, exc: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": exc.__class__.__name__, "message": str(exc)})


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "configuration_version": settings.configuration_version,
        "runtime": {
            "device": hardware.device,
            "vram_gb": hardware.vram_gb,
            "logical_cpus": hardware.logical_cpus,
            "pair_workers": hardware.pair_workers,
            "opencv_threads": hardware.opencv_threads,
            "embedding_batch_size": hardware.embedding_batch_size,
        },
    }


frontend_dist = ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=settings.app.reload,
        reload_dirs=[str(ROOT / "backend"), str(ROOT / "config")],
        reload_includes=["*.py", "*.yaml"],
        reload_excludes=["data/*", "frontend/*"],
        access_log=False,
    )
