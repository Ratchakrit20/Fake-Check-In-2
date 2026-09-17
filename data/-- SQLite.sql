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