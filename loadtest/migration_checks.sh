#!/usr/bin/env bash
# B -> C migration test, data checks, run ON THE VM after the measured load has finished (migration_run_remote.sh does this):
#   ./loadtest/migration_checks.sh
# Compares minihs_src (VM Postgres, untouched since the stop) with minihs_migrated (RDS) for the rows with id <= max_id (the highest id
# at the stop, from cutover_steps.txt): row and device counts, per-device counts, one MD5 over every row, patients, and 1,000 sampled
# rows compared one by one. Rows written after the stop have a higher id and are left out. Writes $OUT/checks.txt (default
# /tmp/migration); exit 0 only if every check passed. Read-only on both databases.
set -u -o pipefail
cd "$(dirname "$0")/.."
. loadtest/migration_lib.sh
OUT=${OUT:-/tmp/migration}
CHECKS=$OUT/checks.txt
max_id=$(grep '^max_id=' "$OUT/cutover_steps.txt" | cut -d= -f2)
[ -n "$max_id" ] || { echo "max_id is missing from $OUT/cutover_steps.txt" >&2; exit 2; }
: > "$CHECKS"
ok=1
compare() {  # compare <name> <sql, with ID_LIMIT> : same answer from the source and from RDS?
    local sql=${2//ID_LIMIT/$max_id} a b
    a=$(echo "$sql" | src_psql) || a="error"; b=$(echo "$sql" | rds_psql) || b="error"
    if [ "$a" = "$b" ] && [ "$a" != error ]; then echo "PASS $1: $a" >> "$CHECKS"
    else echo "FAIL $1: source=$a rds=$b" >> "$CHECKS"; ok=0; fi
}
UTC="SET timezone TO 'UTC';"
compare "rows with id <= $max_id, devices" "SELECT count(*), count(DISTINCT device_id) FROM readings WHERE id <= ID_LIMIT;"
compare "per-device row counts (md5)" "SELECT md5(string_agg(device_id || ':' || n, ',' ORDER BY device_id)) FROM (SELECT device_id, count(*) AS n FROM readings WHERE id <= ID_LIMIT GROUP BY 1) t;"
compare "whole readings table (md5 of every row, by id)" "$UTC SELECT md5(string_agg(md5(r::text), '' ORDER BY id)) FROM readings r WHERE id <= ID_LIMIT;"
compare "patients (md5)" "SELECT md5(string_agg(patient_ref || ':' || name, ',' ORDER BY patient_ref)) FROM patients;"
sample="$UTC SELECT id, r::text FROM readings r WHERE id <= $max_id ORDER BY md5(id::text) LIMIT 1000;"
echo "$sample" | src_psql > "$OUT/sample_source.txt"; echo "$sample" | rds_psql > "$OUT/sample_rds.txt"
n=$(wc -l < "$OUT/sample_source.txt")
if [ "$n" -gt 0 ] && cmp -s "$OUT/sample_source.txt" "$OUT/sample_rds.txt"; then echo "PASS $n sampled rows identical, field by field" >> "$CHECKS"
else echo "FAIL sampled rows differ or none were read ($n rows); see sample_source.txt and sample_rds.txt" >> "$CHECKS"; ok=0; fi

cat "$CHECKS"
[ $ok = 1 ] || { echo "a check FAILED" >&2; exit 1; }
