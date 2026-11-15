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
| App runs on | Laptop, Docker Compose | One EC2 VM (`t3.small`) in **Mumbai (`ap-south-1`)**, same Compose file | EC2 (`t3.small`, Mumbai) plus RDS (`db.t4g.micro`), IoT Core and SQS |
| Load generator | Oracle Cloud ARM box, Mumbai (outside AWS) | same | same |
| Network path | Tailscale tunnel over home Wi-Fi, direct path, ping about 12-14 ms | Internet, same city, ping about 2 ms | Internet, same city: ping to the IoT Core endpoint about 1.1-1.3 ms (VM and IoT Core are both in Mumbai) |
| Encryption | Plain HTTP and plain MQTT (port 1883) inside the Tailscale tunnel | Plain HTTP and plain MQTT | MQTT over TLS (port 8883, IoT Core requires it); the app reads from the queue inside AWS |
| Status | **Done** (2026-11-10) | **Done** (2026-11-12, Mumbai; a `us-east-1` repeat is a team decision) | **Done** (2026-11-14, MQTT only, 21 measured runs; the B-to-C migration test and the cost are still to do) |

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
- Stage A is unencrypted; Stage C includes TLS.
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

### Restart test (MQTT, 100 msg/s, worker stopped for 20 s)

Run on 2026-11-13 with `loadtest/restart_test_remote.sh`; the step times are taken on the VM's clock.

<!-- result_tables: restart stage=B kind=mqtt-100conn-restart -->

| Repeat | Longest gap between stored readings (s) | Sent | Stored | Missing | Lost formula | Seconds above 110% of the rate after restart | Peak stored per second |
|---|---|---|---|---|---|---|---|
| 1 | 21.81 | 12000 | 12000 | 0 | 0 | 15 | 260 |
| 2 | 21.73 | 12000 | 12000 | 0 | 0 | 15 | 266 |
| 3 | 21.74 | 12000 | 12000 | 0 | 0 | 14 | 270 |

<!-- /result_tables -->

### Findings (Stage B)

1. **Up to 100 msg/s nothing was lost, for HTTP or MQTT** (0 missing in all 18 runs). Server time is 2.6-3.9 ms on average,
   about 3 times Stage A's at 50 and 100 msg/s (Stage A: 0.85-1.2 ms). Both stages run the same code and Compose file, so the
   VM (a burstable `t3.small`) saves a reading more slowly than the laptop. At 10 msg/s the two are equal (about 2.9 ms).
2. **HTTP at 500 msg/s overloads this VM.** In all three repeats about two thirds of the 60,000 readings were stored
   (39,322 / 41,461 / 42,730), 56,487 were missing in total, and the generator saw 37,744-39,217 client timeouts (2 s) per run
   against 19,366-22,245 acknowledged. Server time rose to 29-37 ms (p95 108-143 ms) and the median round trip to 205-880 ms. Stage A
   handled the same step with 5 missing readings in total and about 1 ms server time. **The cause is that the VM ran out of CPU.**
   `vmstat` every 5 s over the 24 runs shows the 2-vCPU VM about 84-86% busy in the three runs (user 58-59%, system 25-27%, idle 8-10%),
   11-15 tasks waiting for a CPU on average and about 35,000 context switches per second; at 100 msg/s it was about 25% busy. Swap was
   never used (0 in all 24 runs) and about 1.3 GiB of memory stayed free. The `t3.small` CPU-credit balance (CloudWatch) stayed at
   about 35-38 and never neared 0, so credit throttling is ruled out. The VM stored a flat 305-340 readings/s and kept storing for about
   30 s after the run ended. Rough estimate: about 5 ms of CPU per stored reading on about 1.8 usable cores gives about 350 readings/s.
   **Not isolated:** how the 5 ms splits between web handling, kernel networking and the database was not measured. The whole VM was
   busy, so more `uvicorn` workers on this VM would probably help little; a larger instance or cheaper requests were not tried.
3. **MQTT with 100 connections lost nothing at 500 msg/s, but it did not keep up: the broker's queue absorbed the surplus.** All
   60,000 readings were stored in all three repeats, with server time 2.3 ms (p95 3.1-3.3 ms). The single worker stored only about
   190-225 readings/s (one thread, two database commits per reading, about 4.7 ms each), so storing finished 282-289 s after the first
   reading arrived although the generator sent for 120 s: the last readings waited about 160 s in the broker. Server time (it starts
   when the worker picks a message up) and the generator's round trip (2.2 ms, ending at the broker's acknowledgement) both leave this
   wait out. The VM was only about 29% busy (47% idle, 19-20% disk wait), so the worker was waiting on the disk, not short of CPU. On
   this VM MQTT's ceiling (about 210/s) was lower than HTTP's (about 330/s); the queue is why nothing was lost, since HTTP has none and
   its clients gave up after 2 s. Source: first and last `stored_at` per run and readings stored per 30 s, read from the VM's database.
4. **MQTT's round trip is shorter than HTTP's** at every rate (2.2-2.4 ms against 8.4-8.5 ms up to 100 msg/s) for the same
   reason as in Stage A: it does not include the save. Server time is the fair comparison, and it is about equal up to
   100 msg/s.
5. **Restart test: nothing lost, outage about 22 s.** With the worker stopped for 20 s at 100 msg/s, Mosquitto kept the messages;
   0 of 12,000 readings were missing in all three repeats, and the longest gap between stored readings was 21.73-21.81 s (Stage A:
   21.05-21.16 s). The backlog (about 2,000 queued messages) was stored at peaks of 260 / 266 / 270 readings/s and stayed above 110% of
   the sending rate for 14-15 s (Stage A: peaks 735-760/s, 4-5 s), because the VM saves a reading more slowly (finding 1). The outage itself is the same on both stages; only the catch-up takes about three times as long.
6. **The round trips are not the Mumbai to us-east-1 distance.** Generator and VM are both in Mumbai (ping 2 ms). Compare server
   time and the shape of the curves with Stage C, not the absolute round trips, and say "Stage B (Mumbai)" wherever these numbers are used.

### What these numbers cannot say (Stage B)

- One VM size, one day, one run of each setting (three repeats). The VM was `t3.small`; a larger instance or more `uvicorn`
  workers would move the HTTP 500 msg/s result, and this was not tried.
- Server time is on the VM's clock; the client round trip and ping are on the generator's clock. They are never subtracted.
- The restart test was run with MQTT only (as on Stage A), three repeats at 100 msg/s.
- The cause of the HTTP 500 msg/s failure is the VM's CPU, found from `vmstat` and CloudWatch; the effect of a larger instance or more workers was not measured.
- The MQTT queue delay in finding 3 comes from `stored_at` on the VM's clock only.
- The `vmstat` log stops when the generator stops, so it does not cover the time the MQTT worker spent draining the queue.
- HTTP 500 msg/s repeat 1: the database held 42,842 rows when counted later, 112 more than `run_stats.csv` (42,730), because the server was
  still working through its backlog; that run's "missing" (17,270) is overstated by 112. The other repeats match.

### Cost (Stage B)

**About $0.09 for the performance test window** (EC2 hourly price x hours run), at **Mumbai** list prices, not `us-east-1`. Window:
13:31:36 to 16:31:48 IST = 3.0033 h, including setup and the measured runs.

| Item | Price | Usage | Cost |
|---|---|---|---|
| EC2 `t3.small` | $0.0224/h | 3.0033 h | $0.067 |
| Public IPv4 address | $0.005/h | 3.0033 h | $0.015 |
| EBS gp3 (assumed 20 GB) | $0.0912/GB-month | 3.0033 h | about $0.0075 |
| **Total** | | | **about $0.09** |

**Check against the AWS bill** (November 2026 to 2026-11-13, before credits, from the billing console): $0.13 compute (5.754 instance
hours x $0.0224 = $0.129, so the bill matches usage x list price), $0.73 EC2 - Other, $0.03 IPv4, and RDS, S3 and Secrets Manager at
$0.00, about $0.90 in total. 5.754 h is more than the 3.0 h window because the VM also ran in later sessions. EC2 - Other is almost
all disk: gp3 storage of 7.917 GB-months at $0.0912 = $0.72, because the disk existed for about 12 days, longer than the instance
ran, and keeps billing while the VM is stopped. No data transfer, NAT gateway or snapshot charges appeared. The bill is a check on the
calculation, not a separate finding. The VM is stopped between sessions; while stopped it still bills its disk, and the public IPv4
address is charged while it exists.

## Stage C (EC2 + RDS + IoT Core + SQS)

Run on 2026-11-14 (21 measured runs, all MQTT through IoT Core, 100 connections, 0.5 KB, 120 s each, 3 repeats): the usual matrix of
10/50/100/500 msg/s with one worker (12 runs), the restart test (3 runs) and 500 msg/s with 2 and 4 workers (3 runs each). **Only MQTT was
measured in Stage C; HTTP was measured in Stages A and B only.** Path: generator on the Oracle ARM box (Mumbai) -> IoT Core over TLS (port
8883, QoS 1, one device certificate, client IDs `mini-hs-device-<n>`, topics `mini-hs/vitals/<device_id>`) -> IoT rule -> SQS standard queue
`mini-hs-readings` -> worker on the EC2 `t3.small` (Mumbai) -> RDS `db.t4g.micro` (single-AZ, TLS `verify-full`). The generator waited for the
queue to empty after every run before the next one started (the sampler writes `queue_depth.csv` every 5 s); the two `check` runs
(30 s, 500 msg/s, 1 and 2 workers) from earlier the same day are not in the tables. Workers are added with `docker compose ... --scale worker=N`.

### Matrix (MQTT through IoT Core, 100 connections, 1 worker)

<!-- result_tables: matrix stage=C kinds=mqtt-100conn -->

| Rate (msg/s) | Kind | Runs | Server time avg (ms) | Server time p95 (ms) | Round trip median (ms) | Round trip p95 (ms) | Fastest ping (ms) | Missing (sum) | Lost formula (sum) |
|---|---|---|---|---|---|---|---|---|---|
| 10 | mqtt-100conn | 3 | 4.77 (4.60-4.89) | 5.23 (5.05-5.37) | 14.7 (14.6-14.8) | 19.2 (19.1-19.3) | 1.1 | 0 | 0 |
| 50 | mqtt-100conn | 3 | 4.48 (4.42-4.58) | 5.04 (4.91-5.12) | 14.7 (14.5-15.0) | 19.4 (19.0-19.9) | 1.1 | 0 | 0 |
| 100 | mqtt-100conn | 3 | 4.29 (4.23-4.34) | 4.77 (4.69-4.83) | 14.7 (14.5-15.0) | 19.3 (19.1-19.7) | 1.2 | 0 | 0 |
| 500 | mqtt-100conn | 3 | 4.33 (4.29-4.36) | 4.81 (4.74-4.86) | 14.6 (14.4-14.8) | 19.2 (19.0-19.6) | 1.2 | 0 | 0 |

<!-- /result_tables -->

### Queue and worker scaling (500 msg/s)

<!-- result_tables: queue stage=C kinds=mqtt-100conn,mqtt-100conn-w2,mqtt-100conn-w4 -->

| Workers | Rate (msg/s) | Kind | Runs | Server time avg (ms) | Round trip median (ms) | Round trip p95 (ms) | Queue peak (messages, 5 s samples) | Queue empty after sending stopped (s) | Stored per second | Missing (sum) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | mqtt-100conn | 3 | 4.77 (4.60-4.89) | 14.7 (14.6-14.8) | 19.2 (19.1-19.3) | 0 (0-0) | 23 (15-35) | 10.0 (10.0-10.0) | 0 |
| 1 | 50 | mqtt-100conn | 3 | 4.48 (4.42-4.58) | 14.7 (14.5-15.0) | 19.4 (19.0-19.9) | 19 (16-23) | 30 (25-40) | 49.9 (49.9-49.9) | 0 |
| 1 | 100 | mqtt-100conn | 3 | 4.29 (4.23-4.34) | 14.7 (14.5-15.0) | 19.3 (19.1-19.7) | 406 (368-453) | 35 (30-45) | 96.8 (96.3-97.1) | 0 |
| 1 | 500 | mqtt-100conn | 3 | 4.33 (4.29-4.36) | 14.6 (14.4-14.8) | 19.2 (19.0-19.6) | 47168 (46945-47330) | 442 (436-450) | 104.1 (103.5-105.1) | 0 |
| 2 | 500 | mqtt-100conn-w2 | 3 | 4.32 (4.30-4.34) | 14.4 (14.4-14.5) | 18.9 (18.9-19.0) | 34542 (33993-34939) | 164 (160-166) | 207.6 (206.6-208.2) | 0 |
| 4 | 500 | mqtt-100conn-w4 | 3 | 4.83 (4.77-4.86) | 14.5 (14.5-14.5) | 19.0 (18.9-19.0) | 15060 (14610-15401) | 47 (45-50) | 371.8 (369.0-375.9) | 0 |

<!-- /result_tables -->

### Restart test (MQTT, 100 msg/s, worker stopped for 20 s)

<!-- result_tables: restart stage=C kind=mqtt-100conn-restart -->

| Repeat | Longest gap between stored readings (s) | Sent | Stored | Missing | Lost formula | Seconds above 110% of the rate after restart | Peak stored per second |
|---|---|---|---|---|---|---|---|
| 1 | 23.87 | 12000 | 12000 | 0 | 0 | 0 |  |
| 2 | 22.88 | 12000 | 12000 | 0 | 0 | 0 |  |
| 3 | 22.25 | 12000 | 12000 | 0 | 0 | 1 | 111 |

<!-- /result_tables -->

### Findings (Stage C)

1. **Nothing was lost in any of the 21 runs** (0 missing, 0 by the lost formula, every queue drained). Even at 500 msg/s with one worker,
   which cannot keep up, the readings wait in SQS and are all stored in the end.
2. **One worker stores about 104 readings per second, whatever the load.** At 10 and 50 msg/s it keeps up (10.0 and 49.9 stored per second),
   at 100 msg/s it is at its limit (96.8; the queue peaks at about 400 and empties 35 s after sending stops), and at 500 msg/s it falls behind:
   the queue grows to about 47,000 messages and needs about 442 s after the 120 s of sending to empty. The worker handles one reading at a time
   and `process_reading` commits twice to RDS (insert, then the `stored_at` update), about 4.4 ms each, so it is the worker, not IoT Core or SQS.
   This is the biggest difference from Stage B, where the same 500 msg/s over MQTT was stored without a queue and with 2.3 ms server time.
3. **More workers scale it, but not in a straight line.** At 500 msg/s: 1 worker 104/s, 2 workers 208/s (2.0x), 4 workers 372/s (3.6x). The queue
   peak falls from about 47,000 (1 worker) to 34,500 (2) and 15,000 (4), and the time to empty after sending from 442 s to 164 s and 47 s. Even
   four workers (372/s) are below 500 msg/s, so the queue still builds up. The 4-worker server time rose slightly (4.83 ms against 4.3 ms)
   and its p95 more (6.2 ms against about 4.9 ms). **The CloudWatch graphs show it was not CPU or CPU credits** (finding 4), so the
   remaining suspects are the network round trip of each of the two commits and the workers' own SQS calls; none of these was measured. **The cause of the single worker limit is from reading the code and the stored-per-second numbers, not
   from a profiler.**
4. **Neither machine ran out of CPU, even with 4 workers** (values read off the CloudWatch console graphs, so approximate). The EC2 `t3.small`
   peaked at about 26% CPU (5-minute average, 2 vCPUs) in the 4-worker runs, around 22:25 UTC. The RDS `db.t4g.micro` CPU followed the
   stored rate: about 15% with 1 worker (104/s), about 24% with 2 workers (208/s) and about 40% with 4 workers (372/s) at the
   1-minute peaks. The RDS CPU credit balance fell from about 14.5 to about 7.5 during the 4-worker runs and never reached 0, and the
   surplus credit balance stayed at 0, so no throttling happened. RDS write latency (disk write) was a flat
   0.9-1 ms during all the runs, 4-worker window included, so the disk did not slow down either; the worker sees about 4.4 ms per commit,
   so most of that is not disk. Not looked at: RDS connections and the EC2 credit balance (EC2 CPU credit usage peaked at 2.6, not
   a limit sign at this load).
5. **Server time is 4.3-4.8 ms and does not depend on the rate.** It is about twice Stage B's MQTT figure (2.3-3.0 ms) because each reading
   costs two round trips to a separate RDS machine instead of to a database on the same VM. **It does not include the wait in the queue**:
   `received_at` is stamped when the worker first reads the message, so at 500 msg/s with one worker a reading can wait several minutes
   in SQS and still show about 4 ms. The honest "reading arrives -> reading stored" delay is therefore the queue wait, which can be estimated
   as the queue length divided by the stored rate (about 47,000 / 104 = about 450 s for the last reading of the 1-worker 500 msg/s run) but
   is not measured directly. The generator's clock and the VM's clock are never subtracted.
6. **The client round trip is 14-15 ms (p95 19 ms) at every rate and worker count**, against 2.2-2.4 ms in Stage B. It ends at IoT Core's
   PUBACK, not at the database, and includes the TLS connection to IoT Core, so it says nothing about how long the reading takes to be stored.
   The ping to the IoT endpoint was about 1.1-1.3 ms. All traffic stayed in Mumbai, so none of these numbers show an
   intercontinental round trip.
7. **Restart test: the longest gap between stored readings was 22.3-23.9 s** (worker down 20 s; Stage B 21.7-21.8 s), and nothing was lost:
   while the worker is down the readings wait in the queue (about 2,500 at the peak) and the worker catches up afterwards at its normal
   speed. The "peak stored per second" column is empty or about 111 because a single worker cannot store faster than about 104/s, so the
   Stage B catch-up burst (260-270/s) does not exist here. The queue made the restart safe without needing the broker to redeliver.

### What the Stage C numbers cannot say

- MQTT only; no HTTP numbers for Stage C (neither direct to the API nor over HTTPS through IoT Core).
- The VM and RDS are in Mumbai, like the generator, so these are not the `us-east-1` figures the cost model uses; the Mumbai versus
  `us-east-1` repeat is still a team decision.
- The worker count was tested at 1, 2 and 4 only, on a `t3.small` (2 vCPUs) and a burstable `db.t4g.micro`. CPU, CPU credits and
  RDS disk write latency were not the limit at 4 workers (finding 4), but what is the limit (probably the network round trip of each
  commit, or the SQS calls) is not measured, and 8 workers were not tried.
- Queue peak and drain time come from SQS's approximate counters read every 5 s (they jumped between 0 and thousands in the first seconds of a
  run), so use them as sizes of the effect, not exact values. "Queue empty" means three samples in a row showing 0 visible and 0 in flight.
- Server time leaves out the time in the queue (finding 5); no end-to-end delay from the generator to the database was measured.
- Three repeats per setting; the ranges show the spread. Wi-Fi power save on the laptop was still on during the batch; the laptop only
  started the scripts over SSH, so it is not in any number here.

### Cost (Stage C)

**About $0.98 for the measured window, $1.55 per million messages** (usage x Mumbai list price, before 18% GST and before credits). The
window is the batch of 21 runs, 2026-11-14 20:35:54 to 22:33:22 UTC (1.958 h, from `batch.log`), 633,600 messages through IoT Core.
IoT Core is almost all of it (88%); the machines cost little only because they were counted for the window alone.

| Item | List price (Mumbai) | Usage in the window | Cost |
|---|---|---|---|
| IoT Core messaging | $1.05 per million messages (first billion) | 633,600 messages of 0.5 KB (one 5 KB step each) | $0.665 |
| IoT Core rules triggered | $0.158 per million | 633,600 (one rule, `mini-hs/vitals/+`) | $0.100 |
| IoT Core actions applied | $0.158 per million | 633,600 (one action, send to SQS) | $0.100 |
| SQS | first million requests a month free | send, receive and delete requests, not counted exactly | $0.00 (the bill shows $0.00 for SQS, inside "Others") |
| RDS `db.t4g.micro` | $0.025/h | 1.958 h | $0.049 |
| RDS storage (gp3, 20 GiB) | $0.131 per GB-month | 1.958 h | $0.007 |
| EC2 `t3.small` | $0.0224/h | 1.958 h | $0.044 |
| EC2 disk (gp3, about 20 GB) | $0.0912 per GB-month | 1.958 h | $0.005 |
| Public IPv4 address | $0.005/h | 1.958 h | $0.010 |
| **Total for the window** | | | **$0.980, $1.55 per million messages** |

IoT Core connection minutes (about 11,750 for 100 connections over the window) are not priced here: the price was not looked up and the
amount is immaterial. The 1-worker, 2-worker and 4-worker runs are all in the window, so this is the cost per message of the whole
set, not of one setting.

**Check against the bill (Cost Explorer, 2026-11-15, month to date, before credits):** AWS IoT **$0.91**. The calculation for all the IoT
messages of the month is 663,600 (the 21 runs plus the two 30 s check runs) x ($1.05 + $0.158 + $0.158) per million = **$0.907**;
the rest of the $0.91 is the few thousand messages of earlier tests and the connection minutes. So the IoT bill matches
usage x list price, and the free tier (500,000 messages a month) was not applied to this account. The other lines of the same
bill are month totals and cannot be matched to the window: EC2 compute $0.40, EC2 - Other $0.85 (disk, partly from Stage B), RDS $0.31, VPC $0.10
(public IPv4), others $0.00, **$2.57 in all, covered by credits (net $0.00)**. The bill is a check on the calculation, not a separate finding.

**What the window cost does not include.** The EC2 and RDS were left running from about 17:50 UTC on 2026-11-14 until the user stopped them on
2026-11-15, far longer than the 1.96 h of the runs. The stack (EC2, RDS, disks, IPv4) costs about **$0.0585 per hour** whether or not
messages flow, so each idle hour is about as much as the whole IoT cost of 40,000 messages. The cost per million above assumes the machines
are on only for the runs. At a steady 100 msg/s (360,000 messages an hour) the always-on stack is about $0.16 per million messages, and IoT Core about $1.37
per million, so about $1.53 per million in all, nearly the same as the $1.55 of the measured window.
