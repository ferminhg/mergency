from dataclasses import dataclass


@dataclass(frozen=True)
class TenantConfig:
    installation_id: int
    rolling_window_days: int
    default_team: str
    max_events_per_window: int
