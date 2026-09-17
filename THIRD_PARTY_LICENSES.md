# Third-party licenses

This project prefers permissive open-source dependencies suitable for commercial and internal enterprise use. The list below covers the major direct dependencies. Transitive dependencies remain subject to their own notices; verify the locked dependency set before each production release.

| Dependency | Purpose | License |
|---|---|---|
| Python | Runtime | Python Software Foundation License 2.0 |
| FastAPI | HTTP API | MIT |
| Uvicorn | ASGI server | BSD-3-Clause |
| Pydantic | Configuration and validation | MIT |
| SQLAlchemy | Relational persistence | MIT |
| asyncpg | PostgreSQL driver | Apache-2.0 |
| aiosqlite | Local SQLite adapter | MIT |
| PyYAML | YAML configuration | MIT |
| structlog | Structured logging | Apache-2.0 / MIT |
| Pillow | Image decoding | MIT-CMU |
| ImageHash | Perceptual hashing | BSD-2-Clause |
| NumPy | Numerical operations | BSD-3-Clause |
| OpenCV | SIFT, matching, RANSAC | Apache-2.0 |
| FAISS | Vector search | MIT |
| PyTorch | Model inference | BSD-3-Clause |
| torchvision | Image preprocessing | BSD-3-Clause |
| SSCD code and pretrained weights | Image copy-detection descriptors | MIT |
| Ultralytics | Person and body-part segmentation model runtime | AGPL-3.0 (review deployment obligations; replace with ONNX Runtime when required) |
| Celery | Background jobs | BSD-3-Clause |
| Redis | Queue server | RSALv2 / SSPLv1 (Redis 7 image; review distribution terms) |
| PostgreSQL | Database | PostgreSQL License |
| React | Web UI | MIT |
| React DOM | Web UI rendering | MIT |
| React Router | Web routing | MIT |
| Vite | Frontend build tooling | MIT |
| TypeScript | Frontend language tooling | Apache-2.0 |
| Lucide | Icons | ISC |

Redis 7 is included for local/internal queue operation. Organizations that redistribute or offer Redis as a managed service should conduct a separate license review or replace it through the queue abstraction.
