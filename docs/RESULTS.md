# Results

_Measured results and what they show, one section per stage. The tables between the `result_tables` markers are
generated from the raw run folders with `python loadtest/result_tables.py`; change the text around them, not the
tables. Per-run numbers: `results/run_stats.csv` and `restart_stats.csv`; the raw run folders are archived in the team Drive (see `results/README.md`)._

## How to read the numbers

- **Server time** (ms): how long the app takes from "I got the reading" to "it is saved" (`stored_at - received_at`).
  One machine, one clock. For MQTT it starts when the worker picks the message up, so the wait inside the broker is not in it.
- **Round trip** (ms): the generator's own clock, from sending to the acknowledgement. HTTP waits for the
  database save; MQTT waits only for the broker's PUBACK, so the two are *not* the same event.
- **Fastest ping** (ms): the quickest packet of the baseline ping from the generator to the app. It is the network
  floor for a round trip. The average ping is not used because Wi-Fi power save made it unreliable in some runs (see `GOTCHAS.md`).
- **Missing**: readings the generator sent minus rows stored. **Lost formula**: the per-device gap formula
  `(max(seq) - min(seq) + 1) - count(distinct seq)`, which cannot see readings lost at the end of a device's sequence.
- **Settings of every run:** 0.5 KB messages, 120 s, 100 simulated devices, 3 repeats, a fixed send schedule
  (the generator never waits for a reply before the next send). A cell shows the mean over the repeats and, in brackets,
  the lowest and highest repeat. *Kind* is `http`, or `mqtt-<N>conn` (N MQTT connections).
- **Folder names:** `<date>_<Stage>_<kind>_<rate>per-s_run<n>`; the date is UTC.

## Setup by stage

| | Stage A | Stage B | Stage C |
|---|---|---|---|
| App runs on | Laptop, Docker Compose | One EC2 VM (us-east-1), same Compose file | EC2 plus RDS, IoT Core and SQS |
| Load generator | Oracle Cloud ARM box, Mumbai (outside AWS) | same | same |
| Network path | Tailscale tunnel over home Wi-Fi, direct path, ping about 12-14 ms | Internet, expected about 200-250 ms | Internet, expected about 200-250 ms |
| Encryption | Plain HTTP and plain MQTT (port 1883) inside the Tailscale tunnel | Plain HTTP and plain MQTT | MQTT over TLS (IoT Core requires it) |
| Status | **Done** (2026-11-10) | Not run yet | Not run yet |

## Stage A (laptop)

Conditions: laptop on 5 GHz Wi-Fi close to the router (signal -44 to -52 dBm), checked before every run (router ping
average at most 10 ms, direct Tailscale path). The first matrix (24 runs) used one MQTT connection; after the 20 ms effect
below was found, the MQTT runs were repeated with 100 connections (one per device), which is the fair match to HTTP's
many connections. Both sets are kept.

### HTTP and MQTT (100 connections)

<!-- result_tables: matrix stage=A kinds=http,mqtt-100conn -->

| Rate (msg/s) | Kind | Runs | Server time avg (ms) | Server time p95 (ms) | Round trip median (ms) | Round trip p95 (ms) | Fastest ping (ms) | Missing (sum) | Lost formula (sum) |
|---|---|---|---|---|---|---|---|---|---|
| 10 | http | 3 | 2.95 (2.82-3.03) | 3.95 (3.66-4.18) | 20.7 (20.5-21.1) | 23.4 (23.1-24.0) | 12.5 | 0 | 0 |
| 10 | mqtt-100conn | 3 | 2.95 (2.76-3.05) | 3.80 (3.64-3.97) | 15.2 (14.6-15.5) | 22.4 (17.7-30.2) | 13.0 | 0 | 0 |
| 50 | http | 3 | 1.16 (1.11-1.23) | 1.65 (1.53-1.77) | 17.1 (17.0-17.2) | 19.2 (18.2-19.9) | 12.7 | 1 | 0 |
| 50 | mqtt-100conn | 3 | 1.08 (1.05-1.12) | 1.52 (1.46-1.61) | 14.2 (14.2-14.2) | 17.4 (16.0-19.2) | 13.7 | 0 | 0 |
| 100 | http | 3 | 0.96 (0.92-1.00) | 1.38 (1.29-1.54) | 16.2 (16.2-16.2) | 18.1 (17.8-18.3) | 12.5 | 0 | 0 |
| 100 | mqtt-100conn | 3 | 0.85 (0.78-0.98) | 1.26 (1.03-1.69) | 13.9 (13.8-13.9) | 15.5 (15.1-16.0) | 13.3 | 0 | 0 |
| 500 | http | 3 | 1.11 (1.02-1.26) | 1.80 (1.45-2.49) | 16.4 (16.3-16.4) | 21.6 (18.5-27.9) | 12.2 | 5 | 5 |
| 500 | mqtt-100conn | 3 | 0.72 (0.71-0.72) | 0.95 (0.92-0.97) | 13.8 (13.7-14.1) | 46.3 (15.1-107.0) | 13.0 | 0 | 0 |

<!-- /result_tables -->

### Side result: MQTT with one connection (first matrix)

<!-- result_tables: matrix stage=A kinds=mqtt-1conn -->

| Rate (msg/s) | Kind | Runs | Server time avg (ms) | Server time p95 (ms) | Round trip median (ms) | Round trip p95 (ms) | Fastest ping (ms) | Missing (sum) | Lost formula (sum) |
|---|---|---|---|---|---|---|---|---|---|
| 10 | mqtt-1conn | 3 | 3.04 (3.02-3.08) | 4.19 (3.77-4.47) | 15.3 (14.8-16.2) | 19.3 (16.3-24.8) | 12.7 | 0 | 0 |
| 50 | mqtt-1conn | 3 | 1.21 (1.15-1.28) | 1.82 (1.70-1.95) | 27.2 (14.5-33.7) | 77.4 (16.1-180.3) | 12.5 | 0 | 0 |
| 100 | mqtt-1conn | 3 | 0.89 (0.88-0.90) | 1.38 (1.30-1.44) | 34.7 (34.0-35.9) | 41.3 (40.2-42.3) | 12.6 | 0 | 0 |
| 500 | mqtt-1conn | 3 | 0.70 (0.70-0.71) | 0.92 (0.92-0.93) | 29.0 (26.7-30.6) | 39.3 (39.1-39.6) | 13.0 | 0 | 0 |

<!-- /result_tables -->

### Restart test (MQTT, 100 msg/s, worker stopped for 20 s)

<!-- result_tables: restart stage=A kind=mqtt-100conn-restart -->

| Repeat | Longest gap between stored readings (s) | Sent | Stored | Missing | Lost formula | Seconds above 110% of the rate after restart | Peak stored per second |
|---|---|---|---|---|---|---|---|
| 1 | 21.16 | 12000 | 12000 | 0 | 0 | 5 | 735 |
| 2 | 21.05 | 12000 | 12000 | 0 | 0 | 4 | 760 |
| 3 | 21.08 | 12000 | 12000 | 0 | 0 | 5 | 753 |

<!-- /result_tables -->

### Findings

1. **The app is fast and not stressed.** Server time is about 1 ms from 50 to 500 msg/s (HTTP 0.96-1.16, MQTT 0.72-1.08)
   and about 3 ms at 10 msg/s for both. The laptop CPU was at least 91% idle even at 500 msg/s, and every run reached its
   target rate. The small rise at 10 msg/s is not explained.
2. **HTTP and MQTT save at the same speed.** Server time is equal up to 100 msg/s; at 500 msg/s MQTT is lower
   (0.72 ms against 1.11 ms). This is expected: both call the same `process_reading()` and the same insert.
3. **MQTT's round trip is 2-6 ms shorter than HTTP's** (median 13.8-15.2 ms against 16.2-20.7 ms), close to the
   12-14 ms network floor. Read this with care: MQTT's round trip ends at the broker's acknowledgement, before the save,
   while HTTP's includes the save. HTTP is slowest at 10 msg/s (20.7 ms); the cause is not isolated.
4. **One MQTT connection adds 13-21 ms to the round trip from 50 msg/s upward** (median 27.2 / 34.7 / 29.0 ms at
   50 / 100 / 500 msg/s, against 14.2 / 13.9 / 13.8 ms with 100 connections; no difference at 10 msg/s). Server time did not
   change, so this is a limit of the sender, not of MQTT. The cause is not isolated (small-packet batching on the single TCP
   stream is the likely one). The final comparison therefore uses 100 connections.
5. **Almost nothing was lost.** Of 39 runs, 6 readings were missing, all in two HTTP runs: 5 at 500 msg/s (repeat 3,
   a stall of about 1 s with 11 client timeouts) and 1 at 50 msg/s (repeat 1, the last reading of one device, a connection
   error). The lost formula saw 5 of the 6. The 27 MQTT runs, including the restart test, had none missing.
6. **Short stalls happen on the path.** About 1 s stalls appeared in both protocols (HTTP 500 msg/s repeat 3; MQTT
   500 msg/s repeat 2 with a slowest message of 983 ms, which is why that cell's p95 range is wide). Medians are unaffected.
   Likely Wi-Fi or the Tailscale path; not isolated.
7. **Restart test: nothing lost, outage about 21 s.** With the worker stopped for 20 s at 100 msg/s, Mosquitto kept the
   messages (about 2,050); the longest gap between stored readings was 21.05-21.16 s (the 20 s plus about 1 s to start
   and reconnect), and the backlog was stored at peaks of 735-760 readings per second and cleared within 4-5 s. The sender saw no timeouts, because
   the broker kept acknowledging; readings only reach the database late. Mosquitto's queue limit is raised to 100,000 in
   `infra/mosquitto/mosquitto.conf`; its default (1,000 per client, not tested here) would have been exceeded.
8. **The worker does not stop on request.** `docker compose stop worker` took 10.2 s every time and then killed it,
   so a restart or deploy is a forced kill (the broker redelivers; duplicates are ignored).

### What these numbers cannot say

- They come from one laptop on home Wi-Fi with a 12-14 ms ping. AWS will be about 200-250 ms away, so compare server time
  and the shape of the curves with Stages B and C, not the absolute round trips.
- Stage A is unencrypted; Stage C will include TLS.
- The MQTT round trip and server time leave out the time a message waits in the broker.
- Three repeats per setting; the ranges show the spread. The MQTT 100-connection runs happened later in the evening than
  the HTTP runs, with Wi-Fi power save still on (fixed before the restart test).
- For HTTP, a request that fails with a connection error counts as missing; a real client might retry it.

## Stage B (EC2 lift-and-shift)

Not run yet. When runs exist, add the same two kinds of table (a `matrix` block with `stage=B`, a `restart` block if the
restart test is repeated) and compare with Stage A: the code and the Compose file are the same, so any change in server
time comes from the VM and any change in round trip mostly from the longer network path. Also record the EC2 hours and cost.

## Stage C (EC2 + RDS + IoT Core + SQS)

Not run yet. To add: the same tables with `stage=C`, the B-to-C migration test (data size, copy time, downtime = longest
gap between `stored_at` values at 100 msg/s, row counts, no `seq` gaps, sample rows identical) and the cost per million messages.
