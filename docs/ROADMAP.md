# Roadmap

_Planned-but-not-built features. Do not build unless explicitly asked._

- [x] Small dashboard (latest readings with abnormal highlighted, one chart, counters) — timebox ~2 days, cut first if needed. Built 2026-11-15 as `/dashboard/`.
- [ ] S3 large-file upload.
- [ ] IAM role instead of stored keys.
- [ ] Parameter Store for DB password.
- [ ] CloudTrail logging.
- [ ] Name-free S3 archive.
- [ ] Online B to C migration variant (dump while running, then copy the rows written since): would cut the downtime to seconds; the measured cold cutover is in `docs/RESULTS.md`.
