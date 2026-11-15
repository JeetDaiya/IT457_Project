#!/usr/bin/env bash
# B -> C migration test, step 1, run ON THE VM: reset both databases and seed the source.
#   ./loadtest/migration_prepare.sh [rows_per_device=10000]      100 devices x rows = 1,000,000 readings by default
# Drops and recreates only minihs_src (the VM's Postgres) and drops minihs_migrated (RDS), the two fixed names in
# migration_lib.sh; the Stage B database and the RDS database `minihs` are never touched. Leaves api and worker running
# on minihs_src (the app creates the tables and the 100 synthetic patients at startup), with the seed rows in `readings`:
# device_id seed-dev-0001..0100, patient_ref P0001..P0100, seq 1..rows, stored_at set, values in range (some abnormal).
set -eu -o pipefail
rows=${1:-10000}
case $rows in ''|*[!0-9]*) echo "rows per device must be a number" >&2; exit 2 ;; esac
cd "$(dirname "$0")/.."
. loadtest/migration_lib.sh

echo "$(now) stopping api and worker, starting postgres and mosquitto"
compose "$SRC_URL" stop api worker > /dev/null 2>&1 || true
compose "$SRC_URL" up -d postgres mosquitto > /dev/null
for _ in $(seq 1 60); do
    compose "$SRC_URL" exec -T postgres pg_isready -q -U "$POSTGRES_USER" -d postgres && break; sleep 1
done

echo "$(now) resetting $SRC_DB (VM) and $DST_DB (RDS)"
src_psql postgres <<SQL
DROP DATABASE IF EXISTS $SRC_DB WITH (FORCE);
CREATE DATABASE $SRC_DB;
SQL
rds_psql postgres <<SQL
DROP DATABASE IF EXISTS $DST_DB WITH (FORCE);
SQL

echo "$(now) starting api and worker on $SRC_DB (creates the tables and patients)"
compose "$SRC_URL" up -d --build api worker > /dev/null
wait_for_health 90 || { echo "api does not answer /health on $SRC_DB" >&2; exit 1; }

echo "$(now) seeding 100 devices x $rows readings"
src_psql <<SQL
INSERT INTO readings
    (device_id, patient_ref, heart_rate, spo2, temperature, seq, sent_at, abnormal, received_at, stored_at)
SELECT 'seed-dev-' || lpad(d::text, 4, '0'),
       'P' || lpad(d::text, 4, '0'),
       v.hr, v.sp, v.t, s, v.ts,
       (v.hr < 50 OR v.hr > 120 OR v.sp < 92 OR v.t < 35.5 OR v.t > 38.0),
       v.ts + interval '20 milliseconds', v.ts + interval '25 milliseconds'
FROM generate_series(1, 100) AS d
CROSS JOIN generate_series(1, $rows) AS s
CROSS JOIN LATERAL (SELECT 50 + (d * 7 + s * 13) % 90 AS hr,
                           90 + (d * 3 + s * 5) % 11 AS sp,
                           (35.0 + ((d * 11 + s * 17) % 40) / 10.0)::double precision AS t,
                           timestamptz '2026-11-01 00:00:00+00' + s * interval '1 second'
                               + d * interval '1 millisecond' AS ts) v;
ANALYZE readings;
SQL
echo "$(now) ready: readings rows, devices, database size on $SRC_DB:"
echo "SELECT count(*), count(DISTINCT device_id), pg_size_pretty(pg_database_size(current_database())) FROM readings;" | src_psql
