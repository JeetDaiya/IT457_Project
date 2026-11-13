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
| App runs on | Laptop, Docker Compose | One EC2 VM (`t3.small`) in **Mumbai (`ap-south-1`)**, same Compose file | EC2 plus RDS, IoT Core and SQS |
| Load generator | Oracle Cloud ARM box, Mumbai (outside AWS) | same | same |
| Network path | Tailscale tunnel over home Wi-Fi, direct path, ping about 12-14 ms | Internet, same city, ping about 2 ms | Internet, expected about 200-250 ms if the VM is in `us-east-1` |
| Encryption | Plain HTTP and plain MQTT (port 1883) inside the Tailscale tunnel | Plain HTTP and plain MQTT | MQTT over TLS (IoT Core requires it) |
| Status | **Done** (2026-11-10) | **Done** (2026-11-12, Mumbai; a `us-east-1` repeat is a team decision) | Not run yet |

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

Run on 2026-11-12 (24 runs: HTTP and MQTT with 100 connections, 10/50/100/500 msg/s, 3 repeats, 120 s each). **The VM is in
Mumbai (`ap-south-1`), not `us-east-1`, and so is the generator**, so the network path is short (ping about 2 ms) and the round
trips below say nothing about the Mumbai to us-east-1 distance. The VM is a `t3.small` (2 vCPUs, 2 GiB RAM, a 2 GiB swap file added;
swap was not used), Ubuntu 24.04, the same Compose file as Stage A, one `uvicorn` process for the API and one worker. Runs were started
from the laptop with `loadtest/measure_run_remote.sh`; server time is read on the VM's own clock.

<!-- result_tables: matrix stage=B kinds=http,mqtt-100conn -->

| Rate (msg/s) | Kind | Runs | Server time avg (ms) | Server time p95 (ms) | Round trip median (ms) | Round trip p95 (ms) | Fastest ping (ms) | Missing (sum) | Lost formula (sum) |
|---|---|---|---|---|---|---|---|---|---|
| 10 | http | 3 | 2.86 (2.77-2.92) | 3.60 (3.20-3.88) | 8.5 (8.4-8.8) | 12.2 (10.9-12.9) | 2.0 | 0 | 0 |
| 10 | mqtt-100conn | 3 | 2.96 (2.81-3.26) | 4.37 (3.51-5.33) | 2.4 (2.4-2.4) | 2.8 (2.8-2.9) | 2.0 | 0 | 0 |
| 50 | http | 3 | 3.22 (3.05-3.45) | 3.81 (3.52-3.98) | 8.4 (8.4-8.5) | 12.3 (11.8-13.0) | 2.0 | 0 | 0 |
| 50 | mqtt-100conn | 3 | 2.96 (2.68-3.29) | 4.69 (3.56-6.14) | 2.4 (2.3-2.4) | 3.0 (2.9-3.3) | 2.0 | 0 | 0 |
| 100 | http | 3 | 3.86 (3.31-4.86) | 5.84 (4.05-8.73) | 8.5 (8.3-8.8) | 20.2 (13.5-30.6) | 2.0 | 0 | 0 |
| 100 | mqtt-100conn | 3 | 2.64 (2.56-2.69) | 3.40 (3.12-3.63) | 2.3 (2.3-2.3) | 2.7 (2.6-2.7) | 2.0 | 0 | 0 |
| 500 | http | 3 | 33.81 (28.68-36.61) | 131.33 (108.09-143.03) | 457.3 (204.7-880.3) | 1359.4 (979.6-1901.3) | 1.9 | 56487 | 55932 |
| 500 | mqtt-100conn | 3 | 2.34 (2.31-2.37) | 3.22 (3.11-3.34) | 2.2 (2.2-2.2) | 2.6 (2.5-2.6) | 2.0 | 0 | 0 |

<!-- /result_tables -->

### Findings (Stage B)

1. **Up to 100 msg/s nothing was lost, for HTTP or MQTT** (0 missing in all 18 runs). Server time is 2.6-3.9 ms on average,
   about 3 times Stage A's at 50 and 100 msg/s (Stage A: 0.85-1.2 ms). Both stages run the same code and Compose file, so the
   VM (a burstable `t3.small`) saves a reading more slowly than the laptop. At 10 msg/s the two are equal (about 2.9 ms).
2. **HTTP at 500 msg/s overloads this VM.** In all three repeats about two thirds of the 60,000 readings were stored
   (39,322 / 41,461 / 42,730), 56,487 were missing in total, and the generator saw 37,744-39,217 client timeouts (2 s) per run
   against 19,366-22,245 acknowledged. Server time rose to 29-37 ms (p95 108-143 ms) and the median round trip to 205-880 ms. Stage A
   handled the same step with 5 missing readings in total and about 1 ms server time. On the VM the CPU sampled every 5 s was
   about 70% busy (user and system) averaged over the run and the seconds around it, with no swap use, in the runs inspected
   (HTTP repeats 1 and 3). **The cause is not isolated:** a single `uvicorn` process (one core) is the likely limit; the
   `t3.small` CPU-credit balance was not checked.
3. **MQTT with 100 connections stored all 60,000 readings at 500 msg/s in all three repeats** with server time 2.3 ms (p95 3.1-3.3 ms).
   Read this with care: the generator's round trip ends at the broker's acknowledgement (2.2 ms), and server time starts when the
   worker picks a message up, so neither includes the wait inside the broker. The run was complete only when the worker had stored everything.
4. **MQTT's round trip is shorter than HTTP's** at every rate (2.2-2.4 ms against 8.4-8.5 ms up to 100 msg/s) for the same
   reason as in Stage A: it does not include the save. Server time is the fair comparison, and it is about equal up to
   100 msg/s.
5. **The round trips are not the Mumbai to us-east-1 distance.** Generator and VM are both in Mumbai (ping 2 ms). Compare server
   time and the shape of the curves with Stage C, not the absolute round trips, and say "Stage B (Mumbai)" wherever these numbers are used.

### What these numbers cannot say (Stage B)

- One VM size, one day, one run of each setting (three repeats). The VM was `t3.small`; a larger instance or more `uvicorn`
  workers would move the HTTP 500 msg/s result, and this was not tried.
- Server time is on the VM's clock; the client round trip and ping are on the generator's clock. They are never subtracted.
- No restart test was run on Stage B (`restart_test.sh` is Stage A only).
- The cost of the instance (launched 2026-11-12 13:31 IST) is not recorded here yet.

## Stage C (EC2 + RDS + IoT Core + SQS)

Not run yet. To add: the same tables with `stage=C`, the B-to-C migration test (data size, copy time, downtime = longest
gap between `stored_at` values at 100 msg/s, row counts, no `seq` gaps, sample rows identical) and the cost per million messages.
