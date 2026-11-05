from collections.abc import Mapping
from dataclasses import dataclass

from app.rules import Limits


@dataclass(frozen=True)
class Settings:
    database_url: str
    mqtt_host: str
    mqtt_port: int
    mqtt_topic: str
    heart_rate_min: int
    heart_rate_max: int
    spo2_min: int
    temperature_min: float
    temperature_max: float
    seed_patients: int
    log_level: str

    def limits(self) -> Limits:
        return Limits(
            heart_rate_min=self.heart_rate_min,
            heart_rate_max=self.heart_rate_max,
            spo2_min=self.spo2_min,
            temperature_min=self.temperature_min,
            temperature_max=self.temperature_max,
        )


def load_settings(env: Mapping[str, str]) -> Settings:
    """Build Settings from `env`. Fails loudly on a missing URL or a bad number."""
    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    return Settings(
        database_url=database_url,
        mqtt_host=env.get("MQTT_HOST", "localhost"),
        mqtt_port=_number(env, "MQTT_PORT", "1883", int),
        mqtt_topic=env.get("MQTT_TOPIC", "vitals/#"),
        heart_rate_min=_number(env, "HEART_RATE_MIN", "50", int),
        heart_rate_max=_number(env, "HEART_RATE_MAX", "120", int),
        spo2_min=_number(env, "SPO2_MIN", "92", int),
        temperature_min=_number(env, "TEMPERATURE_MIN", "35.5", float),
        temperature_max=_number(env, "TEMPERATURE_MAX", "38.0", float),
        seed_patients=_number(env, "SEED_PATIENTS", "100", int),
        log_level=env.get("LOG_LEVEL", "INFO"),
    )


def _number[T: (int, float)](
    env: Mapping[str, str], name: str, default: str, kind: type[T]
) -> T:
    raw = env.get(name, default)
    try:
        return kind(raw)
    except ValueError:
        raise ValueError(f"{name} must be a {kind.__name__}, got {raw!r}") from None
