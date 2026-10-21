# Third-party licenses

This table summarizes the major direct runtime dependencies declared in `pyproject.toml`, plus the main frontend packages. `requirements.txt` installs the project in editable mode with its development extras. The repository does not currently include a fully locked transitive dependency set, so verify the resolved packages and their notices for each release.

| Dependency | Purpose | License |
|---|---|---|
| Python | Runtime | Python Software Foundation License 2.0 |
| FastAPI | HTTP API | MIT |
| Uvicorn | ASGI server | BSD-3-Clause |
| python-multipart | Multipart file uploads | Apache-2.0 |
| Pydantic | Configuration and validation | MIT |
| python-dotenv | Environment configuration | BSD-3-Clause |
| SQLAlchemy | Relational persistence | MIT |
| asyncpg | PostgreSQL driver | Apache-2.0 |
| aiosqlite | Local SQLite adapter | MIT |
| PyYAML | YAML configuration | MIT |
| structlog | Structured logging | Apache-2.0 / MIT |
| Pillow | Image decoding | MIT-CMU |
| ImageHash | Perceptual hashing | BSD-2-Clause |
| NumPy | Numerical operations | BSD-3-Clause |
| XlsxWriter | Excel report generation | BSD-2-Clause |
| ReportLab | PDF generation | BSD-3-Clause |
| OpenCV | SIFT, matching, RANSAC | Apache-2.0 |
| FAISS | Vector search | MIT |
| PyTorch | Model inference | BSD-3-Clause |
| torchvision | Image preprocessing | BSD-3-Clause |
| SSCD code and pretrained weights | Image copy-detection descriptors | MIT |
| Ultralytics | Body-part segmentation model runtime | AGPL-3.0 (review deployment obligations; replace with ONNX Runtime when required) |
| Celery | Background jobs | BSD-3-Clause |
| Redis | Queue server | RSALv2 / SSPLv1 (Redis 7 image; review distribution terms) |
| PostgreSQL | Database | PostgreSQL License |
| pytest / pytest-asyncio | Backend tests | MIT |
| httpx | API tests | BSD-3-Clause |
| Ruff | Python linting | MIT |
| React | Web UI | MIT |
| React DOM | Web UI rendering | MIT |
| React Router | Web routing | MIT |
| Vite | Frontend build tooling | MIT |
| TypeScript | Frontend language tooling | Apache-2.0 |
| Lucide | Icons | ISC |

The default local `process` worker mode does not require Redis. Redis is used by the Celery mode configured in `docker-compose.yml`. Organizations that redistribute or offer Redis as a managed service should conduct a separate license review or replace it through the queue abstraction.
