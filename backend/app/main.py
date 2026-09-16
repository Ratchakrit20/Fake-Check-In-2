import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

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


class SPAStaticFiles(StaticFiles):
    """Serve React routes through index.html while preserving real asset 404s."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not Path(path).suffix:
            return await super().get_response("index.html", scope)
        return response


class RequestTooLargeError(Exception):
    pass


class RequestSizeLimitMiddleware:
    """Reject oversized bodies while they stream, before multipart parsing."""

    def __init__(self, application, max_bytes: int) -> None:
        self.application = application
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await JSONResponse({"detail": "request body is too large"}, status_code=413)(scope, receive, send)
                    return
            except ValueError:
                await JSONResponse({"detail": "invalid Content-Length"}, status_code=400)(scope, receive, send)
                return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestTooLargeError
            return message

        try:
            await self.application(scope, limited_receive, send)
        except RequestTooLargeError:
            await JSONResponse({"detail": "request body is too large"}, status_code=413)(scope, receive, send)


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
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.app.max_request_size_mb * 1024 * 1024)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix=settings.app.api_prefix)


@app.exception_handler(ApplicationError)
async def application_error(_: Request, exc: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": exc.__class__.__name__, "message": str(exc)})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'"
    )
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(settings.app.api_prefix) else "no-cache"
    return response


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
    app.mount("/", SPAStaticFiles(directory=frontend_dist, html=True), name="frontend")


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
