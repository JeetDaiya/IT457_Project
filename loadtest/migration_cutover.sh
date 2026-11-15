#!/usr/bin/env bash
# B -> C migration test, the cold cutover, run ON THE VM while the load keeps arriving (loadtest/migration_run_remote.sh starts it).
#   ./loadtest/migration_cutover.sh
# Moves the database minihs_src (VM Postgres) to a new empty database minihs_migrated on RDS and points api and worker at it:
#   prepare  create minihs_migrated on RDS (refuses if it exists; this script never drops anything)
#   stop     api and worker stop (Mosquitto stays up and holds MQTT readings; HTTP requests are refused)
#   dump     pg_dump -Fc of minihs_src          restore  pg_restore, one job, into minihs_migrated
#   start    api and worker start on minihs_migrated; the stopped time ends when /health answers
#   (the data checks are loadtest/migration_checks.sh, run afterwards)
# If anything fails before the start, api and worker are started again on minihs_src and the script exits 1.
# Output in $OUT (default /tmp/migration): cutover_steps.txt (UTC times from the VM clock, the same clock as stored_at,
# plus sizes) and the dump file. Exit 0 if the app answers on the new database.
set -u -o pipefail
cd "$(dirname "$0")/.."
. loadtest/migration_lib.sh
OUT=${OUT:-/tmp/migration}
mkdir -p "$OUT"
STEPS=$OUT/cutover_steps.txt DUMP=$OUT/$SRC_DB.dump
: > "$STEPS"
step() { echo "$1=$(now)" | tee -a "$STEPS"; }
fact() { echo "$1=$2" | tee -a "$STEPS"; }
fail() {
    echo "cutover FAILED: $1" | tee -a "$STEPS" >&2
    compose "$SRC_URL" up -d api worker > /dev/null 2>&1   # back to the old database, which is untouched
    exit 1
}

# ---- prepare (not part of the stopped time) ------------------------------------------------------
wait_for_health 5 || fail "api does not answer /health before the cutover"
echo "SELECT 1;" | rds_psql postgres > /dev/null || fail "RDS is not reachable from the VM"
[ "$(echo "SELECT count(*) FROM pg_database WHERE datname = '$DST_DB';" | rds_psql postgres)" = 0 ] \
    || fail "$DST_DB already exists on RDS (run loadtest/migration_prepare.sh to reset)"
step prepare_start
echo "CREATE DATABASE $DST_DB;" | rds_psql postgres || fail "cannot create $DST_DB on RDS"
step prepare_end

# ---- stopped time: stop, dump, restore, start ---------------------------------------------------
step stop_requested
compose "$SRC_URL" stop api worker > /dev/null 2>&1 || fail "cannot stop api and worker"
step stop_returned
max_id=$(echo "SELECT coalesce(max(id), 0) FROM readings;" | src_psql) || fail "cannot read the source"
fact max_id "$max_id"
fact source_rows "$(echo "SELECT count(*) FROM readings;" | src_psql)"
fact source_db_bytes "$(echo "SELECT pg_database_size('$SRC_DB');" | src_psql)"

step dump_start
compose "$SRC_URL" exec -T postgres pg_dump -U "$POSTGRES_USER" -Fc "$SRC_DB" > "$DUMP" || fail "pg_dump failed"
step dump_end
fact dump_bytes "$(stat -c %s "$DUMP")"

step restore_start
sudo docker run --rm -i -e PGPASSWORD="$RDS_PASSWORD" -v "$RDS_CA_BUNDLE:/ca.pem:ro" postgres:16 \
    pg_restore --no-owner --no-privileges --exit-on-error \
    -d "host=$RDS_HOST user=$RDS_USER dbname=$DST_DB sslmode=verify-full sslrootcert=/ca.pem" < "$DUMP" \
    || fail "pg_restore failed"
step restore_end

step start_requested
compose "$DST_URL" up -d api worker > /dev/null 2>&1 || fail "cannot start api and worker on $DST_DB"
step up_returned
wait_for_health 120 || fail "api does not answer /health on $DST_DB"
step health_ok

python3 loadtest/migration_summary.py steps "$STEPS" 2>/dev/null

# The data checks are a separate script, run after the load has finished: they read every row on both databases and would slow
# the worker (RDS db.t4g.micro) while the measured load is still running (seen in the first full-size run).
exit 0
