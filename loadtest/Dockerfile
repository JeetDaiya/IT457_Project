# Load generator image (Locust + paho-mqtt). Runs on the Oracle ARM box, never on a machine being migrated.
# Build context is the repo root (or ~/it457-loadgen on the box): docker build -f loadtest/Dockerfile -t it457-loadgen .
# Only the dependencies are baked in; loadtest/ and results/ are mounted at run time (see loadtest/README.md).
FROM python:3.12-slim

# iputils-ping: run_http.sh / run_mqtt.sh write the baseline ping to ping.txt, and slim has no ping.
# The Debian 13 package no longer sets cap_net_raw itself and the host disables unprivileged ICMP
# (net.ipv4.ping_group_range), so grant it here (libcap2-bin provides setcap); this lets the
# container run with --user and keep results/ owned by the host user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping libcap2-bin \
    && setcap cap_net_raw+ep /usr/bin/ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY loadtest/requirements.txt loadtest/requirements.txt
RUN pip install --no-cache-dir -r loadtest/requirements.txt
