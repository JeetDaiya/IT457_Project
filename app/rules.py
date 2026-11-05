from dataclasses import dataclass

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Reading(BaseModel):
    """One vital-signs reading. Out-of-range values are rejected (HTTP 422)."""

    model_config = ConfigDict(frozen=True)

    device_id: str = Field(min_length=1)
    patient_ref: str = Field(min_length=1)  # a code such as "P0007", never a name
    heart_rate: int = Field(ge=20, le=250)
    spo2: int = Field(ge=50, le=100)
    temperature: float = Field(ge=30, le=45)
    seq: int = Field(ge=1)
    sent_at: AwareDatetime


@dataclass(frozen=True)
class Limits:
    """Normal ranges. A valid value outside them marks the reading abnormal."""

    heart_rate_min: int
    heart_rate_max: int
    spo2_min: int
    temperature_min: float
    temperature_max: float


def is_abnormal(reading: Reading, limits: Limits) -> bool:
    return (
        not limits.heart_rate_min <= reading.heart_rate <= limits.heart_rate_max
        or reading.spo2 < limits.spo2_min
        or not limits.temperature_min <= reading.temperature <= limits.temperature_max
    )
