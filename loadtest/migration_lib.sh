# Shared by migration_prepare.sh and migration_cutover.sh. Source it from the repo root on the VM (those scripts do the cd):
#   . loadtest/migration_lib.sh
# Needs in .env (see .env.example and infra/docker-compose.stage-c.yml): POSTGRES_USER, POSTGRES_PASSWORD, RDS_HOST,
# RDS_USER, RDS_PASSWORD (URL-safe), RDS_CA_BUNDLE (full path). The two database names are fixed on purpose: they are the only
# databases the migration scripts may drop, so a typo can never reach `minihs` or the Stage B database.
set -a; . ./.env; set +a
SRC_DB=minihs_src          # on the VM's Postgres container: seeded with 1M rows, the app runs on it before the cutover
DST_DB=minihs_migrated     # on RDS: created empty by the cutover, the app runs on it afterwards
SRC_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${SRC_DB}"
DST_URL="postgresql+psycopg2://${RDS_USER}:${RDS_PASSWORD}@${RDS_HOST}:5432/${DST_DB}?sslmode=verify-full&sslrootcert=/certs/global-bundle.pem"

# compose <database url the api and worker use> <docker compose arguments>
compose() {
    local url=$1; shift
    sudo env MIG_DATABASE_URL="$url" docker compose --env-file .env \
        -f infra/docker-compose.yml -f infra/docker-compose.migration.yml "$@"
}
# SQL on stdin. src_psql [database] runs in the Postgres container, rds_psql [database] in a throwaway container with the CA bundle.
src_psql() { compose "$SRC_URL" exec -T postgres psql -q -At -F, -U "$POSTGRES_USER" -d "${1:-$SRC_DB}"; }
rds_psql() {
    sudo docker run --rm -i -e PGPASSWORD="$RDS_PASSWORD" -v "$RDS_CA_BUNDLE:/ca.pem:ro" postgres:16 \
        psql -q -At -F, "host=$RDS_HOST user=$RDS_USER dbname=${1:-$DST_DB} sslmode=verify-full sslrootcert=/ca.pem"
}
now() { date -u +%FT%T.%3NZ; }   # the VM's own clock, the same clock that stamps stored_at
wait_for_health() {  # wait_for_health <max seconds>: polls the api until /health says ok
    local end=$((SECONDS + $1))
    while [ $SECONDS -lt $end ]; do
        curl -s -m 2 http://localhost:8000/health 2>/dev/null | grep -q '"status":"ok"' && return 0
        sleep 0.2
    done
    return 1
}
