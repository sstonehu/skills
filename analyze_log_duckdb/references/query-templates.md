# Query Templates

## Build Hour File List

```bash
for i in 0 1 2 3 4 5; do
  d=$(date -d "$i hour ago" '+/dt-logs/log/mainnet/%Y/%m/%d/%H')
  if [ -d "$d" ]; then
    printf '%s files=%s unreadable=%s\n' "$d" \
      "$(find "$d" -maxdepth 1 -type f -name '*.log*' | wc -l)" \
      "$(find "$d" -maxdepth 1 -type f -name '*.log*' ! -readable | wc -l)"
  fi
done
```

## Import Fixed Hours

```sql
PRAGMA threads=8;
DROP TABLE IF EXISTS raw_logs;
CREATE TABLE raw_logs AS
SELECT
  filename,
  regexp_extract(filename, '/([0-9]{4})/([0-9]{2})/([0-9]{2})/([0-9]{2})/', 4) AS log_hour,
  json
FROM read_json_objects([
  '/dt-logs/log/mainnet/YYYY/MM/DD/HH/*.log*'
], format='newline_delimited', filename=true);

DROP VIEW IF EXISTS parsed_logs;
CREATE VIEW parsed_logs AS
SELECT
  filename,
  log_hour,
  json_extract_string(json, '$.timestamp') AS ts,
  json_extract_string(json, '$.podName') AS pod_name,
  json_extract_string(json, '$.tag') AS tag,
  coalesce(json_extract_string(json, '$.timeRecord.source'), '<null>') AS source,
  coalesce(json_extract_string(json, '$.timeRecord.liquidityType'), '<null>') AS liquidity_type,
  try_cast(json_extract_string(json, '$.message.blockNumber') AS BIGINT) AS message_block_number,
  try_cast(json_extract_string(json, '$.message.block') AS BIGINT) AS message_block,
  try_cast(json_extract_string(json, '$.timeRecord.blockNumber') AS BIGINT) AS time_record_block_number,
  try_cast(json_extract_string(json, '$.timeRecord.blockHash') AS BIGINT) AS time_record_block_hash_num,
  json_extract_string(json, '$.timeRecord.blockHash') AS time_record_block_hash,
  json
FROM raw_logs;
```

## Count A Tag

```sql
SELECT count(*) AS rows
FROM parsed_logs
WHERE tag = 'mevListener.poolPaths';

SELECT log_hour, count(*) AS cnt
FROM parsed_logs
WHERE tag = 'mevListener.poolPaths'
GROUP BY log_hour
ORDER BY log_hour;
```

## Source And Liquidity Distribution

```sql
SELECT
  source,
  liquidity_type,
  count(*) AS cnt,
  round(count(*) * 100.0 / sum(count(*)) OVER (), 4) AS pct
FROM parsed_logs
WHERE tag = 'builder.getPaths'
GROUP BY source, liquidity_type
ORDER BY cnt DESC, source, liquidity_type;
```

## Target Block Lookup

```sql
SELECT tag, log_hour, count(*) AS cnt, min(ts) AS first_ts, max(ts) AS last_ts
FROM parsed_logs
WHERE json::VARCHAR LIKE '%25139307%'
GROUP BY tag, log_hour
ORDER BY first_ts, tag;
```

For precise matching, prefer parsed block fields:

```sql
SELECT tag, log_hour, count(*) AS cnt, min(ts), max(ts)
FROM parsed_logs
WHERE time_record_block_hash_num = 25139307
   OR time_record_block_number = 25139307
   OR message_block_number = 25139307
   OR message_block = 25139307
GROUP BY tag, log_hour
ORDER BY min(ts), tag;
```

## Builder BuildResult CycleId Duplication

`targetRoute` currently has no explicit `id`; construct one from pool id/address, from token, to token, and direction.

```sql
DROP TABLE IF EXISTS tmp_target_route_cycleids;
CREATE TABLE tmp_target_route_cycleids AS
WITH build_rows AS (
  SELECT
    row_number() OVER () AS row_id,
    ts,
    time_record_block_hash AS block_hash,
    coalesce(
      json_extract_string(json, '$.message.targetRoute.Pool.poolId'),
      json_extract_string(json, '$.message.targetRoute.Pool.poolAddress')
    ) || '|' ||
    coalesce(json_extract_string(json, '$.message.targetRoute.FromToken.address'), '') || '|' ||
    coalesce(json_extract_string(json, '$.message.targetRoute.ToToken.address'), '') || '|' ||
    coalesce(json_extract_string(json, '$.message.targetRoute.IsFwd'), '') AS target_route_id,
    try_cast(json_extract_string(json, '$.message.duralPaths') AS BIGINT) AS dural_paths,
    json_extract(json, '$.message.cycleIds') AS cycle_ids
  FROM parsed_logs
  WHERE tag='builder.buildResult'
    AND time_record_block_hash IS NOT NULL
    AND json_array_length(json, '$.message.cycleIds') IS NOT NULL
)
SELECT
  row_id,
  ts,
  block_hash,
  target_route_id,
  dural_paths,
  unnest(json_extract(cycle_ids, '$[*]'))::UBIGINT AS cycle_id
FROM build_rows;
```

Per block:

```sql
WITH route_counts AS (
  SELECT block_hash, count(DISTINCT target_route_id) AS target_routes, count(DISTINCT row_id) AS build_result_rows
  FROM tmp_target_route_cycleids
  GROUP BY block_hash
), cycle_counts AS (
  SELECT block_hash, count(*) AS cycle_ids_total, count(DISTINCT cycle_id) AS cycle_ids_distinct
  FROM tmp_target_route_cycleids
  GROUP BY block_hash
)
SELECT
  c.block_hash,
  r.build_result_rows,
  r.target_routes,
  c.cycle_ids_total,
  c.cycle_ids_distinct,
  c.cycle_ids_total - c.cycle_ids_distinct AS duplicate_cycle_ids,
  round((c.cycle_ids_total - c.cycle_ids_distinct)::DOUBLE / nullif(c.cycle_ids_total, 0), 6) AS duplicate_rate
FROM cycle_counts c
JOIN route_counts r USING (block_hash)
WHERE r.target_routes > 1
ORDER BY duplicate_rate DESC, duplicate_cycle_ids DESC;
```

Overall:

```sql
WITH route_counts AS (
  SELECT block_hash, count(DISTINCT target_route_id) AS target_routes
  FROM tmp_target_route_cycleids
  GROUP BY block_hash
), cycle_counts AS (
  SELECT block_hash, count(*) AS total_ids, count(DISTINCT cycle_id) AS distinct_ids
  FROM tmp_target_route_cycleids
  GROUP BY block_hash
), per_block AS (
  SELECT c.*
  FROM cycle_counts c
  JOIN route_counts r USING (block_hash)
  WHERE r.target_routes > 1
)
SELECT
  count(*) AS blocks,
  sum(total_ids) AS cycle_ids_total,
  sum(distinct_ids) AS cycle_ids_distinct_sum_by_block,
  sum(total_ids - distinct_ids) AS duplicate_cycle_ids,
  round(sum(total_ids - distinct_ids)::DOUBLE / nullif(sum(total_ids), 0), 6) AS duplicate_rate_weighted,
  round(avg((total_ids - distinct_ids)::DOUBLE / nullif(total_ids, 0)), 6) AS duplicate_rate_avg_by_block
FROM per_block;
```
