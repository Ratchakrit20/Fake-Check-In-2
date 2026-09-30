# Production database schema

The application currently supports SQLite for a single-machine installation and PostgreSQL for production. Keep image bytes in object storage (S3, MinIO, or equivalent); the database stores only the immutable storage key and metadata.

## Core tables

| Table | Purpose | Important columns |
| --- | --- | --- |
| `analysis_jobs` | One processing request from this UI or an external system | `id`, `status`, `total`, `processed`, `created_at`, `started_at`, `completed_at`, `error` |
| `images` | An uploaded evidence image | `id`, `original_filename`, `source_job_number`, `source_checkin_date`, `storage_path`, `sha256`, `phash`, dimensions, MIME type, analysis status |
| `analysis_job_items` | Links each submitted image to a processing job | `job_id`, `image_id`, `position`, `status` |
| `image_embeddings` | Versioned vector embedding per image/model | `image_id`, `embedding`, `model_name`, `model_version`, `configuration_version` |
| `pairwise_results` | One normalized relationship edge per image pair | `image_a_id`, `image_b_id`, score, classification, metrics, JSON evidence |

## Relationships and indexes

```text
analysis_jobs 1 ──< analysis_job_items >── 1 images
images        1 ──< image_embeddings
images        1 ──< pairwise_results >── 1 images
```

`images.source_job_number` and `images.source_checkin_date` are indexed so external systems can retrieve evidence by job number or check-in date. New files named `new_YYYYMMDD_*_home_<10-digit-job>_*` (or `splitter`) are parsed at upload. Existing historical records are parsed from their original filename in API responses, so no data is lost during migration.

## External API boundary

External websites must communicate only through `/api/v1`, never by sharing the database. Submit images to create a job, poll `/api/v1/jobs/{id}`, and retrieve group/image data from the API. This keeps the processing service replaceable and lets the UI evolve independently.

## Production requirements

- Use PostgreSQL, database migrations (Alembic), object storage, and a Redis/Celery worker rather than in-process background tasks.
- Add an `external_request_id` and `source_system` to `analysis_jobs` before integrating a caller, then make the pair unique for safe retries.
- Store credentials and connection strings in environment variables or a secret manager; never commit them.
- Version models and threshold configuration with each result, which the existing embedding/result metadata already supports.
