# Image Relation Inspector

ระบบตรวจภาพซ้ำ ภาพดัดแปลง ภาพครอป/เบลอ ภาพกลับด้าน และกลุ่มภาพสัมพันธ์ด้วย SHA-256, pHash, DINOv2, FAISS, SIFT, RANSAC และโมเดลแยกอวัยวะ

คู่มือภาษาไทยฉบับเต็ม รวมสถาปัตยกรรม รายละเอียดทุกโมดูล การติดตั้ง GPU และการย้ายเครื่อง: [PROJECT_GUIDE_TH.md](PROJECT_GUIDE_TH.md)

Production-oriented MVP for explainable, multi-signal image relationship analysis. It detects exact duplicates, perceptually modified images, global semantic similarity, local feature overlap, geometric transformations, crops, and horizontal mirrors without treating one model score as proof.

## Architecture

```text
Upload -> validation -> SHA-256 -> pHash -> DINOv2 -> FAISS candidates
                                                     -> SIFT -> RANSAC
                                                     -> score fusion -> graph groups
```

FastAPI owns the HTTP interface, SQLAlchemy persists metadata and evidence, and React supplies the operator interface. Local mode runs batch jobs in a background thread without requiring Redis. Celery/Redis is an optional production extension. Algorithms are isolated behind focused components and replaceable interfaces. Existing fingerprints and embeddings are retained so new images can be processed incrementally.

## Environment

```powershell
conda create -n fake-check-in -c conda-forge --override-channels python=3.11 pip nodejs=22 -y
conda activate fake-check-in
python -m pip install -e ".[dev]"
```

DINOv2 downloads its Apache-2.0 model from the official `facebookresearch/dinov2` Torch Hub repository on first use. The writable cache is `data/models/torch`. Set `EMBEDDING__DEVICE=cpu`, `cuda`, or `auto`. CUDA falls back to CPU only when `allow_cpu_fallback` is enabled.

Build the frontend once:

```powershell
cd frontend
npm install
npm run build
cd ..
```

Start the application with Python:

```powershell
python -m backend.app.main
```

Development auto-reload is enabled in `config/default.yaml`. Production and Docker set `APP__RELOAD=false`.

Optional: start a Celery worker only for a deployment that has been wired to Redis. It is not required by the current local batch route:

```powershell
python -m celery -A backend.app.workers.celery_app worker --loglevel=INFO
```

Open `http://127.0.0.1:8000`. API documentation is at `/docs`.

## Configuration

The single source of truth is `config/default.yaml`. Environment overrides use `SECTION__FIELD`, for example `VECTOR_SEARCH__TOP_K=100`. Configuration is strongly validated and invalid thresholds fail during startup. `.env.example` contains production service overrides.

## API

- `GET /health`
- `GET /api/v1/dashboard`
- `POST /api/v1/images`
- `GET /api/v1/images/{id}`
- `POST /api/v1/compare`
- `POST /api/v1/batches`
- `GET /api/v1/jobs/{id}`
- `GET /api/v1/groups`

## Tests

```powershell
python -m pytest
python -m ruff check backend tests
```

## Docker

`docker compose up --build` starts the API, worker, PostgreSQL, and Redis. The image starts runtime services through Python commands.

## Known limitations

- The first DINOv2 request needs model download access and is slower than later requests.
- Manipulation localization is an extension point and is intentionally not presented as definitive AI-image detection.
- Batch upload persistence and worker submission require the deployment-specific durable upload adapter before large production workloads.
- The local FAISS index is single-host; use a replaceable distributed vector store for multi-worker deployments.
- Thresholds require calibration with representative organizational evidence images before enforcement decisions.

See `THIRD_PARTY_LICENSES.md` before enterprise deployment.
