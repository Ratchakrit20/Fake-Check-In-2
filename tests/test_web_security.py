from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.app.main import RequestSizeLimitMiddleware, app


def test_security_headers_and_spa_fallback():
    response = TestClient(app).get("/compare")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_request_size_limit_rejects_body_before_endpoint():
    tiny = FastAPI()
    tiny.add_middleware(RequestSizeLimitMiddleware, max_bytes=4)

    @tiny.post("/")
    async def consume(request: Request):
        return {"length": len(await request.body())}

    response = TestClient(tiny).post("/", content=b"12345")

    assert response.status_code == 413
