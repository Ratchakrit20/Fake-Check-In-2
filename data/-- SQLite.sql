-- SQLite
WITH extracted AS (
    SELECT
        id,
        original_filename,
        substr(
            original_filename,
            instr(lower(original_filename), 'home_') + 5,
            10
        ) AS source_number
    FROM images
    WHERE instr(lower(original_filename), 'home_') > 0
)
SELECT
    source_number,
    COUNT(*) AS image_count
FROM extracted
WHERE length(source_number) = 10
  AND source_number NOT GLOB '*[^0-9]*'
GROUP BY source_number
ORDER BY image_count DESC, source_number;

WITH extracted AS (
    SELECT substr(
        original_filename,
        instr(lower(original_filename), 'home_') + 5,
        10
    ) AS source_number
    FROM images
    WHERE instr(lower(original_filename), 'home_') > 0
)
SELECT COUNT(DISTINCT source_number) AS source_number_count
FROM extracted
WHERE length(source_number) = 10
  AND source_number NOT GLOB '*[^0-9]*';


SELECT
  CASE
    WHEN instr(original_filename, '_') > 0
      THEN substr(original_filename, 1, instr(original_filename, '_') - 1)
    ELSE original_filename
  END AS filename_prefix,
  COUNT(*) AS image_count
FROM images
GROUP BY filename_prefix
ORDER BY image_count DESC;

SELECT
    id,
    status,
    processed,
    total,
    error,
    created_at,
    started_at,
    completed_at,
    duration_seconds
FROM analysis_jobs
LIMIT 15;