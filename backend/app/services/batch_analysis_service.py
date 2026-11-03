from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy import select, update

from ..core.config import get_settings
from ..core.runtime import detect_hardware
from ..db.models import AnalysisJob, AnalysisJobItem, ImageEmbedding, ImageRecord, PairwiseResult
from ..db.session import SessionFactory
from ..detectors.perceptual_hash_detector import PerceptualHashDetector
from ..domain.enums import JobStatus
from ..embeddings.sscd import SSCDEmbeddingProvider
from ..storage.local_storage import LocalImageStorage
from ..vector_store.faiss_store import FaissVectorStore
from ..vector_store.phash_index import PerceptualHashIndex
from .ai_image_metadata import serialize_ai_metadata
from .image_quality_service import UNVERIFIABLE, ImageQualityAssessment, ImageQualityService
from .image_source_service import resolve_image_source
from .job_process_lock import job_process_lock
from .pair_analysis_service import PairAnalysisService

logger = logging.getLogger(__name__)

_PHASH_ROTATION_ANGLES = (0, 90, 180, 270)


def _stored_phash_rotations(record: ImageRecord) -> dict[str, str]:
    try:
        values = json.loads(record.phash_rotations_json or "{}")
    except (TypeError, ValueError):
        values = {}
    if isinstance(values, dict) and all(str(angle) in values for angle in _PHASH_ROTATION_ANGLES):
        return {str(angle): str(values[str(angle)]) for angle in _PHASH_ROTATION_ANGLES}
    return {"0": record.phash} if record.phash else {}


def _rotation_embedding_model_name(model_name: str, angle: int) -> str:
    return f"{model_name}__rotcw_{angle}"


def _cosine_similarity(first: np.ndarray, second: np.ndarray) -> float:
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    return float(np.dot(first, second) / max(denominator, 1e-12))


def _best_phash_alignment(
    current_hashes: dict[str, str],
    candidate_hashes: dict[str, str],
    distance,
) -> tuple[int, int, int] | None:
    """Return (distance, current rotation, candidate rotation) for best match."""
    best: tuple[int, int, int] | None = None
    for current_angle, current_hash in current_hashes.items():
        for candidate_angle, candidate_hash in candidate_hashes.items():
            current_degrees = int(current_angle)
            candidate_degrees = int(candidate_angle)
            item = (distance(current_hash, candidate_hash), current_degrees, candidate_degrees)
            if best is None or item < best:
                best = item
    return best


def same_submission(first: ImageRecord, second: ImageRecord) -> bool:
    """Skip images from the same Customer ID on the same check-in date.

    Technician ID is retained only as source metadata. It must not influence
    candidate selection or create additional relationships.
    """
    first_reference = resolve_image_source(first)
    second_reference = resolve_image_source(second)
    return (
        first_reference.customer_id is not None
        and second_reference.customer_id is not None
        and first_reference.checkin_date is not None
        and second_reference.checkin_date is not None
        and first_reference.customer_id == second_reference.customer_id
        and first_reference.checkin_date == second_reference.checkin_date
    )


@lru_cache
def _components() -> tuple[SSCDEmbeddingProvider, FaissVectorStore, PairAnalysisService]:
    settings = get_settings()
    provider = SSCDEmbeddingProvider(
        settings.embedding.model_path,
        settings.embedding.model_url,
        settings.embedding.model_sha256,
        settings.embedding.device,
        settings.embedding.normalize,
        settings.embedding.allow_cpu_fallback,
        settings.embedding.input_size,
    )
    vector_store = FaissVectorStore(
        provider.dimension,
        settings.vector_search.index_path,
        settings.vector_search.metadata_path,
    )
    return provider, vector_store, PairAnalysisService(settings, provider)


def normalize_pair(first: str, second: str) -> tuple[str, str]:
    return (first, second) if first < second else (second, first)


def unique_records_by_id(records: Iterable[ImageRecord]) -> list[ImageRecord]:
    """Keep one record per image when a batch contains exact duplicate files."""
    return list({record.id: record for record in records}.values())


async def _set_job(job_id: str, status: JobStatus, processed: int | None = None, error: str | None = None) -> None:
    async with SessionFactory() as session:
        job = await session.get(AnalysisJob, job_id)
        if job is None:
            return
        # The cancellation endpoint owns the terminal state. A worker which
        # finishes its current CPU task afterwards must not turn it back into
        # COMPLETED or FAILED.
        if job.status == JobStatus.CANCELLED.value and status != JobStatus.CANCELLED:
            return
        now = datetime.now(UTC).replace(tzinfo=None)
        if status == JobStatus.EMBEDDING and job.started_at is None:
            job.started_at = now
        if status not in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}:
            job.completed_at = None
            job.duration_seconds = None
        if status in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}:
            job.completed_at = now
            started_at = job.started_at or job.created_at
            job.duration_seconds = max(0.0, (now - started_at).total_seconds())
        job.status = status.value
        if processed is not None:
            job.processed = processed
        job.error = error
        await session.commit()


async def _cancel_requested(job_id: str) -> bool:
    """Read the persisted cancellation flag between safe processing units."""
    async with SessionFactory() as session:
        job = await session.get(AnalysisJob, job_id)
        return job is None or job.status == JobStatus.CANCELLED.value


async def _preflight_image_quality(
    job_id: str,
    all_records: dict[str, ImageRecord],
    record_paths: dict[str, Path],
    settings,
) -> set[str]:
    """Classify legacy records once so unusable images never enter either index."""
    service = ImageQualityService(settings.image_quality)
    pending = [
        record for record in all_records.values()
        if record.image_quality_status is None and record.id in record_paths
    ]
    updates: list[tuple[ImageRecord, ImageQualityAssessment]] = []
    for index, record in enumerate(pending, start=1):
        if index % 250 == 0 and await _cancel_requested(job_id):
            raise RuntimeError("analysis job cancelled during image-quality preflight")
        try:
            with Image.open(record_paths[record.id]) as opened:
                assessment = service.assess(opened)
        except (OSError, ValueError):
            logger.exception("image quality preflight could not decode %s", record.id)
            assessment = ImageQualityAssessment(UNVERIFIABLE, "image_decode_failed", 1.0)
        record.image_quality_status = assessment.status
        record.image_quality_reason = assessment.reason
        record.near_black_ratio = assessment.near_black_ratio
        if assessment.status == UNVERIFIABLE:
            record.analysis_status = UNVERIFIABLE
        updates.append((record, assessment))
        if len(updates) >= 250:
            async with SessionFactory() as session:
                for updated_record, result in updates:
                    await session.execute(
                        update(ImageRecord)
                        .where(ImageRecord.id == updated_record.id)
                        .values(
                            image_quality_status=result.status,
                            image_quality_reason=result.reason,
                            near_black_ratio=result.near_black_ratio,
                            analysis_status=UNVERIFIABLE if result.status == UNVERIFIABLE else updated_record.analysis_status,
                        )
                    )
                await session.commit()
            logger.info("image quality preflight: checked %d/%d legacy images", index, len(pending))
            updates.clear()
    if updates:
        async with SessionFactory() as session:
            for updated_record, result in updates:
                await session.execute(
                    update(ImageRecord)
                    .where(ImageRecord.id == updated_record.id)
                    .values(
                        image_quality_status=result.status,
                        image_quality_reason=result.reason,
                        near_black_ratio=result.near_black_ratio,
                        analysis_status=UNVERIFIABLE if result.status == UNVERIFIABLE else updated_record.analysis_status,
                    )
                )
            await session.commit()
        logger.info("image quality preflight: checked %d/%d legacy images", len(pending), len(pending))
    unverifiable_ids = {
        image_id for image_id, record in all_records.items()
        if record.image_quality_status == UNVERIFIABLE
    }
    logger.info("image quality preflight complete: %d images excluded from matching", len(unverifiable_ids))
    return unverifiable_ids


async def _backfill_phash_rotations(
    job_id: str,
    all_records: dict[str, ImageRecord],
    record_paths: dict[str, Path],
    settings,
) -> set[str]:
    """Calculate four canonical pHashes once for legacy verifiable images."""
    detector = PerceptualHashDetector(settings.phash.hash_size, settings.flip_detection.horizontal)
    pending = [
        record
        for record in all_records.values()
        if record.image_quality_status != UNVERIFIABLE
        and record.id in record_paths
        and len(_stored_phash_rotations(record)) != len(_PHASH_ROTATION_ANGLES)
    ]
    newly_unverifiable: set[str] = set()
    batch_size = 250
    for offset in range(0, len(pending), batch_size):
        if await _cancel_requested(job_id):
            raise RuntimeError("analysis job cancelled during pHash rotation backfill")
        updates: list[tuple[ImageRecord, dict[str, str] | None, ImageQualityAssessment | None]] = []
        for record in pending[offset : offset + batch_size]:
            try:
                with Image.open(record_paths[record.id]) as opened:
                    assessment = ImageQualityService(settings.image_quality).assess(opened)
                    rotations = detector.calculate_rotations(opened) if assessment.can_compare else None
            except (OSError, ValueError):
                logger.exception("pHash rotation backfill could not decode %s", record.id)
                assessment = ImageQualityAssessment(UNVERIFIABLE, "image_decode_failed", 1.0)
                rotations = None
            if not assessment.can_compare:
                newly_unverifiable.add(record.id)
                record.image_quality_status = assessment.status
                record.image_quality_reason = assessment.reason
                record.near_black_ratio = assessment.near_black_ratio
                record.analysis_status = UNVERIFIABLE
            else:
                record.phash = rotations["0"]
                record.phash_rotations_json = json.dumps(rotations, separators=(",", ":"))
            updates.append((record, rotations, assessment if not assessment.can_compare else None))

        async with SessionFactory() as session:
            for record, rotations, assessment in updates:
                values = {}
                if assessment is not None:
                    values.update(
                        image_quality_status=assessment.status,
                        image_quality_reason=assessment.reason,
                        near_black_ratio=assessment.near_black_ratio,
                        analysis_status=UNVERIFIABLE,
                        phash=None,
                        phash_rotations_json=None,
                    )
                elif rotations is not None:
                    values.update(
                        phash=rotations["0"],
                        phash_rotations_json=json.dumps(rotations, separators=(",", ":")),
                    )
                await session.execute(update(ImageRecord).where(ImageRecord.id == record.id).values(**values))
            await session.commit()
        logger.info(
            "pHash rotation backfill: checked %d/%d legacy images",
            min(offset + batch_size, len(pending)),
            len(pending),
        )
    logger.info(
        "pHash rotation backfill complete: %d images updated, %d excluded as unverifiable",
        len(pending) - len(newly_unverifiable),
        len(newly_unverifiable),
    )
    return newly_unverifiable


async def process_batch_job(job_id: str, force: bool = False) -> None:
    settings = get_settings()
    profile = detect_hardware(
        settings.performance.cpu_workers,
        settings.performance.opencv_threads,
        settings.embedding.batch_size,
    )
    import cv2

    cv2.setNumThreads(profile.opencv_threads)
    provider, vector_store, pair_service = _components()
    storage = LocalImageStorage(settings.storage.root)
    try:
        if await _cancel_requested(job_id):
            return
        # Preserve the last persisted progress during recovery/resume. The
        # completed item rows below are the checkpoint used to reconcile it.
        await _set_job(job_id, JobStatus.VALIDATING)
        async with SessionFactory() as session:
            items = list(
                await session.scalars(
                    select(AnalysisJobItem).where(AnalysisJobItem.job_id == job_id).order_by(AnalysisJobItem.position)
                )
            )
            all_records = {record.id: record for record in await session.scalars(select(ImageRecord))}
            record_paths = {
                image_id: resolved
                for image_id, record in all_records.items()
                if (resolved := storage.resolve(image_id, record.storage_path)) is not None
            }
        # Older library images have no quality status yet. Check them once
        # before building either candidate index; the result is persisted.
        unverifiable_ids = await _preflight_image_quality(job_id, all_records, record_paths, settings)
        unverifiable_ids.update(
            await _backfill_phash_rotations(job_id, all_records, record_paths, settings)
        )
        skipped_items = [
            item for item in items
            if item.status != JobStatus.COMPLETED.value and item.image_id in unverifiable_ids
        ]
        if skipped_items:
            async with SessionFactory() as session:
                for item in skipped_items:
                    item_row = await session.get(AnalysisJobItem, item.id)
                    if item_row:
                        item_row.status = JobStatus.COMPLETED.value
                await session.commit()
            for item in skipped_items:
                item.status = JobStatus.COMPLETED.value
        completed_items = [item for item in items if item.status == JobStatus.COMPLETED.value]
        pending_items = [
            item for item in items
            if item.status != JobStatus.COMPLETED.value and item.image_id not in unverifiable_ids
        ]
        await _set_job(job_id, JobStatus.EMBEDDING, len(completed_items))
        records_by_sha: dict[str, list[str]] = {}
        for record in all_records.values():
            if record.image_quality_status != UNVERIFIABLE:
                records_by_sha.setdefault(record.sha256, []).append(record.id)
        phash_items = [
            (record.id, hash_value)
            for record in all_records.values()
            if record.image_quality_status != UNVERIFIABLE
            for hash_value in _stored_phash_rotations(record).values()
        ]
        phash_index = PerceptualHashIndex.from_items(phash_items, pair_service.phash.distance)
        eligible_image_ids = [
            image_id
            for image_id in all_records
            if image_id in record_paths and image_id not in unverifiable_ids
        ]
        item_image_ids = list(dict.fromkeys(
            item.image_id
            for item in items
            if item.image_id not in unverifiable_ids and item.image_id in record_paths
        ))
        async with SessionFactory() as session:
            vectors: dict[str, np.ndarray] = {}
            embedding_rows: list[ImageEmbedding] = []
            # Keep each IN clause below SQLite's older parameter limit while
            # replacing one database round trip per image with chunked reads.
            for id_offset in range(0, len(eligible_image_ids), 500):
                embedding_rows.extend(
                    await session.scalars(
                        select(ImageEmbedding).where(
                            ImageEmbedding.image_id.in_(eligible_image_ids[id_offset : id_offset + 500]),
                            ImageEmbedding.model_name == settings.embedding.model,
                            ImageEmbedding.model_version == settings.embedding.version,
                        )
                    )
                )
            embeddings_by_image = {row.image_id: row for row in embedding_rows}
            for image_id, embedding_row in embeddings_by_image.items():
                vectors[image_id] = np.frombuffer(embedding_row.embedding, dtype=np.float32).copy()

            batch_size = profile.embedding_batch_size
            missing = unique_records_by_id([
                all_records[image_id]
                for image_id in item_image_ids
                if image_id not in vectors and image_id in all_records
            ])
            embedding_rows_since_commit = 0
            for offset in range(0, len(missing), batch_size):
                if await _cancel_requested(job_id):
                    return
                records_chunk = missing[offset : offset + batch_size]
                images: list[Image.Image] = []
                for record in records_chunk:
                    with Image.open(record_paths[record.id]) as opened:
                        images.append(ImageOps.exif_transpose(opened).convert("RGB"))
                batch_vectors = provider.embed_many(images)
                for record, vector in zip(records_chunk, batch_vectors):
                    vectors[record.id] = vector
                    session.add(
                        ImageEmbedding(
                            image_id=record.id,
                            embedding=vector.astype(np.float32).tobytes(),
                            model_name=settings.embedding.model,
                            model_version=settings.embedding.version,
                            configuration_version=settings.configuration_version,
                        )
                    )
                embedding_rows_since_commit += len(records_chunk)
                if embedding_rows_since_commit >= 64:
                    await session.commit()
                    embedding_rows_since_commit = 0
            if embedding_rows_since_commit:
                await session.commit()

        vector_store.remove_many(unverifiable_ids)
        vector_store.add_many([(image_id, vectors[image_id]) for image_id in item_image_ids if image_id in vectors])
        async with SessionFactory() as session:
            existing_rows = list(await session.scalars(select(PairwiseResult)))
            retained_rows: list[PairwiseResult] = []
            for row in existing_rows:
                first, second = all_records.get(row.image_a_id), all_records.get(row.image_b_id)
                if first is not None and second is not None and same_submission(first, second):
                    await session.delete(row)
                else:
                    retained_rows.append(row)
            await session.commit()
            existing_rows = retained_rows
        existing_ids = {normalize_pair(row.image_a_id, row.image_b_id): row.id for row in existing_rows}
        seen_pairs = set() if force else set(existing_ids)
        await _set_job(job_id, JobStatus.VERIFYING, len(completed_items))

        loop = asyncio.get_running_loop()
        rotated_embedding_cache: dict[tuple[str, int], np.ndarray] = {}
        with ThreadPoolExecutor(max_workers=profile.pair_workers, thread_name_prefix="pair-analysis") as executor:
            for offset, item in enumerate(pending_items, start=1):
                if await _cancel_requested(job_id):
                    return
                current = all_records.get(item.image_id)
                if current is None:
                    continue
                vector = vectors.get(current.id)
                if vector is None:
                    continue
                current_path = record_paths.get(current.id)
                if current_path is None:
                    continue
                async with SessionFactory() as session:
                    item_row = await session.get(AnalysisJobItem, item.id)
                    if item_row:
                        item_row.status = "PROCESSING"
                        await session.commit()
                current_bytes = current_path.read_bytes()
                candidates = vector_store.search(vector, settings.vector_search.top_k)
                topk_scores = {candidate_id: float(similarity) for candidate_id, similarity in candidates}
                candidate_scores: dict[str, float] = {}
                candidate_sources: dict[str, set[str]] = {}
                candidate_evidence: dict[str, dict[str, int]] = {}
                threshold = settings.performance.candidate_min_similarity
                for candidate_id, similarity in topk_scores.items():
                    if candidate_id != current.id and similarity >= threshold:
                        candidate_scores[candidate_id] = similarity
                        candidate_sources.setdefault(candidate_id, set()).add("sscd_top_k")
                        logger.info(
                            "candidate gate passed source=sscd_top_k image_id=%s candidate_id=%s sscd=%.4f threshold=%.4f",
                            current.id,
                            candidate_id,
                            similarity,
                            threshold,
                        )

                current_hashes = _stored_phash_rotations(current)
                phash_hits: set[str] = set()
                for hash_value in current_hashes.values():
                    phash_hits.update(
                        phash_index.search(hash_value, settings.phash.max_hamming_distance)
                    )
                phash_alignments: dict[str, tuple[int, int, int]] = {}
                for candidate_id in phash_hits:
                    candidate = all_records.get(candidate_id)
                    candidate_path = record_paths.get(candidate_id)
                    if (
                        candidate is None
                        or candidate_id == current.id
                        or candidate_path is None
                        or candidate.image_quality_status == UNVERIFIABLE
                        or same_submission(current, candidate)
                        or normalize_pair(current.id, candidate_id) in seen_pairs
                    ):
                        continue
                    candidate_hashes = _stored_phash_rotations(candidate)
                    alignment = _best_phash_alignment(
                        current_hashes,
                        candidate_hashes,
                        pair_service.phash.distance,
                    )
                    if alignment is not None and alignment[0] <= settings.phash.max_hamming_distance:
                        phash_alignments[candidate_id] = alignment
                        candidate_evidence[candidate_id] = {
                            "phash_candidate_distance": alignment[0],
                            "phash_current_rotation": alignment[1],
                            "phash_candidate_rotation": alignment[2],
                        }

                missing_candidate_records = unique_records_by_id([
                    all_records[candidate_id]
                    for candidate_id in phash_alignments
                    if candidate_id not in vectors
                ])
                for offset in range(0, len(missing_candidate_records), profile.embedding_batch_size):
                    missing_chunk = missing_candidate_records[offset : offset + profile.embedding_batch_size]
                    decoded_images: list[Image.Image] = []
                    for record in missing_chunk:
                        with Image.open(record_paths[record.id]) as opened:
                            decoded_images.append(ImageOps.exif_transpose(opened).convert("RGB"))
                    batch_vectors = provider.embed_many(decoded_images)
                    async with SessionFactory() as session:
                        for record, missing_vector in zip(missing_chunk, batch_vectors):
                            vectors[record.id] = missing_vector
                            session.add(
                                ImageEmbedding(
                                    image_id=record.id,
                                    embedding=missing_vector.astype(np.float32).tobytes(),
                                    model_name=settings.embedding.model,
                                    model_version=settings.embedding.version,
                                    configuration_version=settings.configuration_version,
                                )
                            )
                        await session.commit()
                    vector_store.add_many([(record.id, vectors[record.id]) for record in missing_chunk])

                rotated_pairs: list[tuple[str, int, int]] = []
                for candidate_id, alignment in phash_alignments.items():
                    candidate_vector = vectors.get(candidate_id)
                    if candidate_vector is None:
                        continue
                    base_similarity = _cosine_similarity(vector, candidate_vector)
                    if base_similarity >= threshold:
                        candidate_scores[candidate_id] = base_similarity
                        candidate_sources.setdefault(candidate_id, set()).add("phash_and_sscd")
                        logger.info(
                            "candidate gate passed source=phash_and_sscd image_id=%s candidate_id=%s sscd=%.4f threshold=%.4f phash_distance=%d rotations=%d:%d",
                            current.id,
                            candidate_id,
                            base_similarity,
                            threshold,
                            alignment[0],
                            alignment[1],
                            alignment[2],
                        )
                        continue
                    _, current_rotation, candidate_rotation = alignment
                    if current_rotation == candidate_rotation:
                        continue
                    rotated_pairs.append((candidate_id, current_rotation, candidate_rotation))

                rotation_model_names = {
                    angle: _rotation_embedding_model_name(settings.embedding.model, angle)
                    for angle in _PHASH_ROTATION_ANGLES
                }
                needed_rotation_keys = {
                    key
                    for candidate_id, current_rotation, candidate_rotation in rotated_pairs
                    for key in ((current.id, current_rotation), (candidate_id, candidate_rotation))
                }
                uncached_keys = needed_rotation_keys - rotated_embedding_cache.keys()
                if uncached_keys:
                    rotation_image_ids = sorted({image_id for image_id, _ in uncached_keys})
                    async with SessionFactory() as session:
                        for id_offset in range(0, len(rotation_image_ids), 500):
                            rows = await session.scalars(
                                select(ImageEmbedding).where(
                                    ImageEmbedding.image_id.in_(rotation_image_ids[id_offset : id_offset + 500]),
                                    ImageEmbedding.model_name.in_(list(rotation_model_names.values())),
                                    ImageEmbedding.model_version == settings.embedding.version,
                                )
                            )
                            name_to_angle = {name: angle for angle, name in rotation_model_names.items()}
                            for row in rows:
                                angle = name_to_angle[row.model_name]
                                rotated_embedding_cache[(row.image_id, angle)] = np.frombuffer(
                                    row.embedding, dtype=np.float32
                                ).copy()
                    uncached_keys = needed_rotation_keys - rotated_embedding_cache.keys()
                    missing_rotation_specs = sorted(uncached_keys)
                    for offset in range(0, len(missing_rotation_specs), profile.embedding_batch_size):
                        specs = missing_rotation_specs[offset : offset + profile.embedding_batch_size]
                        rotated_images: list[Image.Image] = []
                        for image_id, angle in specs:
                            with Image.open(record_paths[image_id]) as opened:
                                rotated_images.append(
                                    pair_service.phash.rotate_clockwise(opened, angle)
                                )
                        rotation_vectors = provider.embed_many(rotated_images)
                        async with SessionFactory() as session:
                            for (image_id, angle), rotation_vector in zip(specs, rotation_vectors):
                                rotated_embedding_cache[(image_id, angle)] = rotation_vector
                                session.add(
                                    ImageEmbedding(
                                        image_id=image_id,
                                        embedding=rotation_vector.astype(np.float32).tobytes(),
                                        model_name=rotation_model_names[angle],
                                        model_version=settings.embedding.version,
                                        configuration_version=settings.configuration_version,
                                    )
                                )
                            await session.commit()

                for candidate_id, current_rotation, candidate_rotation in rotated_pairs:
                    current_rotation_vector = rotated_embedding_cache.get((current.id, current_rotation))
                    candidate_rotation_vector = rotated_embedding_cache.get((candidate_id, candidate_rotation))
                    if current_rotation_vector is None or candidate_rotation_vector is None:
                        continue
                    similarity = _cosine_similarity(current_rotation_vector, candidate_rotation_vector)
                    if similarity >= threshold:
                        candidate_scores[candidate_id] = similarity
                        candidate_sources.setdefault(candidate_id, set()).add("phash_and_rotated_sscd")
                        alignment = phash_alignments[candidate_id]
                        logger.info(
                            "candidate gate passed source=phash_and_rotated_sscd image_id=%s candidate_id=%s sscd=%.4f threshold=%.4f phash_distance=%d rotations=%d:%d",
                            current.id,
                            candidate_id,
                            similarity,
                            threshold,
                            alignment[0],
                            current_rotation,
                            candidate_rotation,
                        )

                # Exact-byte duplicates are reported directly, without SIFT/RANSAC.
                exact_duplicate_ids = set(records_by_sha.get(current.sha256, []))
                for duplicate_id in exact_duplicate_ids:
                    if duplicate_id != current.id:
                        candidate_scores[duplicate_id] = 1.0
                        candidate_sources.setdefault(duplicate_id, set()).add("sha256_exact")
                        logger.info(
                            "candidate gate passed source=sha256_exact image_id=%s candidate_id=%s",
                            current.id,
                            duplicate_id,
                        )

                with Image.open(io.BytesIO(current_bytes)) as opened_current:
                    current_image = ImageOps.exif_transpose(opened_current).convert("RGB")
                ai_metadata_json = serialize_ai_metadata(pair_service.ai_models.report_metadata(current_image))
                work: list[tuple[tuple[str, str], str, float, dict[str, object]]] = []
                for candidate_id, similarity in candidate_scores.items():
                    if candidate_id == current.id:
                        continue
                    pair = normalize_pair(current.id, candidate_id)
                    if pair in seen_pairs:
                        logger.info(
                            "candidate skipped image_id=%s candidate_id=%s reason=pair_already_recorded_or_seen",
                            current.id,
                            candidate_id,
                        )
                        continue
                    candidate = all_records.get(candidate_id)
                    candidate_path = record_paths.get(candidate_id)
                    if candidate is None or candidate_path is None:
                        continue
                    if candidate.image_quality_status == UNVERIFIABLE:
                        continue
                    if same_submission(current, candidate):
                        logger.info(
                            "candidate skipped image_id=%s candidate_id=%s reason=same_submission",
                            current.id,
                            candidate_id,
                        )
                        continue
                    seen_pairs.add(pair)
                    metadata = {
                        "sources": sorted(candidate_sources.get(candidate_id, set())),
                        **candidate_evidence.get(candidate_id, {}),
                    }
                    logger.info(
                        "candidate accepted image_id=%s image=%s candidate_id=%s candidate=%s sources=%s sscd=%.4f phash_distance=%s current_rotation=%s candidate_rotation=%s",
                        current.id,
                        current.original_filename,
                        candidate.id,
                        candidate.original_filename,
                        ",".join(metadata["sources"]),
                        similarity,
                        metadata.get("phash_candidate_distance", "-"),
                        metadata.get("phash_current_rotation", "-"),
                        metadata.get("phash_candidate_rotation", "-"),
                    )
                    work.append((
                        pair,
                        str(candidate_path),
                        similarity,
                        metadata,
                    ))

                logger.info(
                    "candidate selection image=%s top_k=%d sscd_pass=%d phash_hits=%d phash_sscd_pass=%d sha_exact=%d accepted=%d",
                    current.id,
                    len(topk_scores),
                    sum(1 for score in topk_scores.values() if score >= threshold),
                    len(phash_hits),
                    sum(1 for source in candidate_sources.values() if "phash_and_sscd" in source or "phash_and_rotated_sscd" in source),
                    len(exact_duplicate_ids),
                    len(work),
                )

                for offset in range(0, len(work), settings.performance.pair_chunk_size):
                    if await _cancel_requested(job_id):
                        return
                    chunk = work[offset : offset + settings.performance.pair_chunk_size]
                    futures = []
                    for _, candidate_path, similarity, metadata in chunk:
                        if "sha256_exact" in metadata["sources"]:
                            futures.append(asyncio.sleep(0, result=pair_service.exact_duplicate_result()))
                        else:
                            futures.append(loop.run_in_executor(
                                executor,
                                pair_service.analyze_bytes,
                                current_bytes,
                                Path(candidate_path).read_bytes(),
                                similarity,
                            ))
                    results = await asyncio.gather(*futures)
                    async with SessionFactory() as session:
                        existing_pair_ids = {
                            existing_ids[pair]
                            for pair, _, _, _ in chunk
                            if pair in existing_ids
                        }
                        existing_pairs = list(
                            await session.scalars(
                                select(PairwiseResult).where(PairwiseResult.id.in_(existing_pair_ids))
                            )
                        ) if existing_pair_ids else []
                        existing_pairs_by_id = {row.id: row for row in existing_pairs}
                        for (pair, _, _, candidate_info), result in zip(chunk, results):
                            result_details = result.model_dump(mode="json")
                            result_evidence = result_details.setdefault("evidence", {})
                            result_evidence["candidate_sources"] = candidate_info["sources"]
                            for key in (
                                "phash_candidate_distance",
                                "phash_current_rotation",
                                "phash_candidate_rotation",
                            ):
                                if key in candidate_info:
                                    result_evidence[key] = candidate_info[key]
                            evidence = result.evidence
                            logger.info(
                                "candidate pair result image_a_id=%s image_b_id=%s sources=%s classification=%s score=%.4f sift_matches=%d ransac_inliers=%d inlier_ratio=%.4f",
                                pair[0],
                                pair[1],
                                ",".join(candidate_info["sources"]),
                                result.classification.value,
                                result.score,
                                int(evidence.get("sift_good_matches", 0)),
                                int(evidence.get("ransac_inliers", 0)),
                                float(evidence.get("ransac_inlier_ratio", 0)),
                            )
                            values = {
                                "phash_distance": evidence.get("phash_distance"),
                                "dino_similarity": evidence.get("embedding_similarity"),
                                "sift_matches": int(evidence.get("sift_good_matches", 0)),
                                "ransac_inliers": int(evidence.get("ransac_inliers", 0)),
                                "ransac_inlier_ratio": float(evidence.get("ransac_inlier_ratio", 0)),
                                "flip_detected": int(bool(evidence.get("flip_detected"))),
                                "relationship_score": result.score,
                                "relationship_level": result.classification.value,
                                "details_json": json.dumps(result_details, ensure_ascii=False),
                            }
                            existing_id = existing_ids.get(pair)
                            existing_pair = existing_pairs_by_id.get(existing_id) if existing_id else None
                            if existing_pair is None:
                                existing_pair = PairwiseResult(image_a_id=pair[0], image_b_id=pair[1], **values)
                                session.add(existing_pair)
                            else:
                                for field, value in values.items():
                                    setattr(existing_pair, field, value)
                        await session.commit()

                async with SessionFactory() as session:
                    current_row = await session.get(ImageRecord, current.id)
                    if current_row:
                        current_row.analysis_status = "COMPLETED"
                        current_row.analyzed_at = datetime.now(UTC)
                        current_row.ai_metadata_json = ai_metadata_json
                    item_row = await session.get(AnalysisJobItem, item.id)
                    if item_row:
                        item_row.status = JobStatus.COMPLETED.value
                    await session.commit()
                await _set_job(job_id, JobStatus.VERIFYING, len(completed_items) + offset)
        await _set_job(job_id, JobStatus.COMPLETED, len(items))
    except Exception as exc:  # noqa: BLE001 - job boundary must persist every failure
        if await _cancel_requested(job_id):
            return
        if "cannot schedule new futures after shutdown" in str(exc):
            await _set_job(job_id, JobStatus.INTERRUPTED, error="worker interrupted; resume from checkpoint")
            return
        await _set_job(job_id, JobStatus.FAILED, error=str(exc))


def run_batch_job(job_id: str, force: bool = False) -> bool:
    with job_process_lock(job_id) as acquired:
        if not acquired:
            logger.info("job %s is already running in another process", job_id)
            return False
        asyncio.run(process_batch_job(job_id, force=force))
        return True
