# Gotchas

_Things that have bitten us or are easy to get wrong. Updated in place._

- **Never subtract timestamps from two different machines.** Server delay = `stored_at − received_at`. Client round-trip = generator's own clock. Report baseline `ping` separately.
- **Never commit `.env`, certs, or private keys.** Use `.env.example` as the template.
- **Duplicate `(device_id, seq)` is not an error** — return 200, not 4xx (MQTT QoS 1 can redeliver).
- **AWS region is always `us-east-1`** — cost model is priced there.
