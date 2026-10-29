-- SQLite
-- WITH extracted AS (
--     SELECT
--         id,
--         original_filename,
--         substr(
--             original_filename,
--             instr(lower(original_filename), 'home_') + 5,
--             10
--         ) AS source_number
--     FROM images
--     WHERE instr(lower(original_filename), 'home_') > 0
-- )
-- SELECT
--     source_number,
--     COUNT(*) AS image_count
-- FROM extracted
-- WHERE length(source_number) = 10
--   AND source_number NOT GLOB '*[^0-9]*'
-- GROUP BY source_number
-- ORDER BY image_count DESC, source_number;

-- WITH extracted AS (
--     SELECT substr(
--         original_filename,
--         instr(lower(original_filename), 'home_') + 5,
--         10
--     ) AS source_number
--     FROM images
--     WHERE instr(lower(original_filename), 'home_') > 0
-- )
-- SELECT COUNT(DISTINCT source_number) AS source_number_count
-- FROM extracted
-- WHERE length(source_number) = 10
--   AND source_number NOT GLOB '*[^0-9]*';


-- SELECT
--   CASE
--     WHEN instr(original_filename, '_') > 0
--       THEN substr(original_filename, 1, instr(original_filename, '_') - 1)
--     ELSE original_filename
--   END AS filename_prefix,
--   COUNT(*) AS image_count
-- FROM images
-- GROUP BY filename_prefix
-- ORDER BY image_count DESC;

-- SELECT
--     id,
--     status,
--     processed,
--     total,
--     error,
--     created_at,
--     started_at,
--     completed_at,
--     duration_seconds
-- FROM analysis_jobs
-- LIMIT 15;


SELECT
    p.id AS pair_id,
    -- a.original_filename AS image_a,
    a.source_checkin_date AS image_a_date,
    a.source_job_number AS image_a_customer_id,
    -- b.original_filename AS image_b,
    b.source_checkin_date AS image_b_date,
    b.source_job_number AS image_b_customer_id,
    p.relationship_score,
    p.sift_matches,
    p.ransac_inliers,
    p.ransac_inlier_ratio,
    p.details_json
FROM pairwise_results AS p
JOIN images AS a ON a.id = p.image_a_id
JOIN images AS b ON b.id = p.image_b_id
WHERE p.relationship_level = 'unrelated'
  AND (
      (a.analyzed_at >= '2026-10-27 17:00:00'
       AND a.analyzed_at < '2026-10-28 17:00:00')
      OR
      (b.analyzed_at >= '2026-10-27 17:00:00'
       AND b.analyzed_at < '2026-10-28 17:00:00')
  )
ORDER BY p.created_at DESC;

-- SELECT
--     id,
--     original_filename,
--     storage_path,
--     image_quality_reason,
--     near_black_ratio
-- FROM images
-- WHERE image_quality_status = 'UNVERIFIABLE'
-- ORDER BY near_black_ratio DESC;

-- SELECT id, status, processed, total, created_at, started_at
-- FROM analysis_jobs
-- WHERE UPPER(status) IN (
--   'QUEUED', 'RUNNING', 'VALIDATING', 'EMBEDDING', 'VERIFYING'
-- )
-- ORDER BY created_at DESC;


-- DELETE FROM pairwise_results;

SELECT COUNT(*) AS pair_count FROM pairwise_results;

-- SELECT id, status, processed, total, created_at
-- FROM analysis_jobs
-- ORDER BY created_at DESC
-- LIMIT 5;

-- DELETE FROM analysis_job_items
-- WHERE job_id IN (
--     SELECT id FROM analysis_jobs
--     WHERE UPPER(status) = 'CANCELLED'
-- );

-- DELETE FROM analysis_jobs
-- WHERE UPPER(status) = 'CANCELLED';

-- SELECT id, status, processed, total, created_at
-- FROM analysis_jobs
-- WHERE UPPER(status) = 'CANCELLED'
-- ORDER BY created_at DESC;
SELECT
    COUNT(*) AS scanned_images,
    SUM(
        CASE
            WHEN json_array_length(json_extract(ai_metadata_json, '$.datetime')) > 0
            THEN 1 ELSE 0
        END
    ) AS images_with_datetime
FROM images
WHERE json_valid(ai_metadata_json)
  AND json_extract(ai_metadata_json, '$.model') = 'lat-long/v1';