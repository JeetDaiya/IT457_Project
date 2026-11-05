# Deployment

## Currently running AWS resources

**None** — Stage A runs locally via Docker Compose.

## Stage A (local)

- `infra/docker-compose.yml`: PostgreSQL, Mosquitto, `api` and `worker` containers.
- Setup: `cp .env.example .env`, then from the repo root:
  `docker compose --env-file .env -f infra/docker-compose.yml up --build`
- Stop with `docker compose --env-file .env -f infra/docker-compose.yml down` (add `-v` to wipe the data volumes).
- Ports on the host: 8000 (API), 1883 (MQTT), 5432 (Postgres; set `POSTGRES_HOST_PORT` if a local PostgreSQL uses it).

## Stage B (EC2)

_Not yet deployed._ Same Compose file as Stage A.

- **Decide when deploying:** whether to publish Postgres (5432) on the VM at all. Anonymous MQTT (1883) must also be restricted by security group or given auth before the Oracle generator connects.

## Stage C (EC2 + managed services)

_Not yet deployed._
