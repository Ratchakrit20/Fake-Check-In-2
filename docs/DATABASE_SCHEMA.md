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
| `export_reports` | One generated relationship report | `id`, `date_from`, `date_to`, `pdf_path`, `created_at` |
| `export_report_images` | Immutable snapshot of evidence images included in a report | `export_report_id`, `image_id`, `source_job_number` (Customer ID), `source_checkin_date`, `group_id_snapshot` |

## Relationships and indexes

```text
analysis_jobs 1 ──< analysis_job_items >── 1 images
images        1 ──< image_embeddings
images        1 ──< pairwise_results >── 1 images
export_reports 1 ──< export_report_images >── 1 images
```

`images.source_job_number` and `images.source_checkin_date` are indexed so external systems can retrieve evidence by job number or check-in date. New files named `new_YYYYMMDD_*_home_<10-digit-job>_*` (or `splitter`) are parsed at upload. Existing historical records are parsed from their original filename in API responses, so no data is lost during migration.

`source_job_number` is displayed in the UI and PDF as **Customer ID**. The database column deliberately retains its old technical name so existing records and integrations continue to work.

## Resumable analysis jobs

`analysis_job_items.status` is the durable checkpoint for batch analysis. Each item moves from `QUEUED` to `PROCESSING` and then `COMPLETED`; a resumed job processes only items not marked `COMPLETED`. If a worker shuts down during pair analysis, the job is marked `INTERRUPTED` and can be resumed through `POST /api/v1/jobs/{job_id}/resume`. This avoids recomputing completed images after a restart or power interruption.

## Export report snapshot

When a PDF is generated, `export_reports` records the actual first and last check-in dates represented by its evidence, rather than only the filter dates selected in the UI. `export_report_images` stores every image included and its `group_id_snapshot`. This preserves the evidence and group membership that existed at export time, even if relationship grouping changes later.

## Adding a new field

For every new persisted field, update these layers together:

1. `backend/app/db/models.py` - add the SQLAlchemy column and its index/constraint when needed.
2. `backend/app/db/session.py` - add a safe migration for existing SQLite/PostgreSQL databases. `Base.metadata.create_all()` only creates a new table; it does not add a new column to an existing table.
3. `backend/app/domain/schemas.py` - add request/response validation when the field crosses the API boundary.
4. Relevant API route/service - read/write the field, for example `backend/app/api/routes/batches.py` for image ingestion or `backend/app/api/routes/exports.py` for report data.
5. `frontend/src/api/client.ts` and the relevant page/component - add the TypeScript type and visual control only if the UI needs it.
6. This document - keep the production schema and field purpose current.

## External API boundary

External websites must communicate only through `/api/v1`, never by sharing the database. Submit images to create a job, poll `/api/v1/jobs/{id}`, and retrieve group/image data from the API. This keeps the processing service replaceable and lets the UI evolve independently.

## Production requirements

- Use PostgreSQL, database migrations (Alembic), object storage, and a Redis/Celery worker rather than in-process background tasks.
- Add an `external_request_id` and `source_system` to `analysis_jobs` before integrating a caller, then make the pair unique for safe retries.
- Store credentials and connection strings in environment variables or a secret manager; never commit them.
- Version models and threshold configuration with each result, which the existing embedding/result metadata already supports.
