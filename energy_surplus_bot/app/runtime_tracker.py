from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.models import DeviceConfig, TimeWindow


def parse_hhmm(value: str) -> int:
    hour_text, minute_text = value.split(":", 1)
    return int(hour_text) * 60 + int(minute_text)


def minutes_since_midnight(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def is_within_window(window: TimeWindow, moment: datetime) -> bool:
    start = parse_hhmm(window.start)
    end = parse_hhmm(window.end)
    current = minutes_since_midnight(moment)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def minutes_until_window_end(window: TimeWindow, moment: datetime) -> int:
    end = parse_hhmm(window.end)
    current = minutes_since_midnight(moment)
    if parse_hhmm(window.start) == end:
        return 24 * 60
    if current <= end:
        return end - current
    return (24 * 60 - current) + end


def elapsed_minutes(started_at: datetime | None, now: datetime) -> int:
    if started_at is None:
        return 0
    return max(0, int((now - started_at).total_seconds() // 60))


@dataclass
class RuntimeEntry:
    device_name: str
    day: str
    runtime_today_minutes: int = 0
    last_started_at: datetime | None = None
    last_stopped_at: datetime | None = None

    @classmethod
    def for_today(cls, device_name: str, today: date) -> RuntimeEntry:
        return cls(device_name=device_name, day=today.isoformat())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeEntry:
        return cls(
            device_name=str(data["device_name"]),
            day=str(data["day"]),
            runtime_today_minutes=int(data.get("runtime_today_minutes", 0)),
            last_started_at=_parse_datetime(data.get("last_started_at")),
            last_stopped_at=_parse_datetime(data.get("last_stopped_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_name": self.device_name,
            "day": self.day,
            "runtime_today_minutes": self.runtime_today_minutes,
            "last_started_at": _format_datetime(self.last_started_at),
            "last_stopped_at": _format_datetime(self.last_stopped_at),
        }

    def normalized_for(self, today: date) -> RuntimeEntry:
        if self.day == today.isoformat():
            return self
        return RuntimeEntry.for_today(self.device_name, today)

    def runtime_with_current_session(self, is_on: bool, now: datetime) -> int:
        if not is_on:
            return self.runtime_today_minutes
        return self.runtime_today_minutes + elapsed_minutes(self.last_started_at, now)

    def has_met_min_run(self, device: DeviceConfig, is_on: bool, now: datetime) -> bool:
        if not is_on:
            return True
        return elapsed_minutes(self.last_started_at, now) >= device.min_run_minutes

    def has_met_min_off(self, device: DeviceConfig, now: datetime) -> bool:
        if self.last_stopped_at is None:
            return True
        return elapsed_minutes(self.last_stopped_at, now) >= device.min_off_minutes


@dataclass
class RuntimeState:
    entries: dict[str, RuntimeEntry] = field(default_factory=dict)

    @classmethod
    def empty_for_devices(cls, devices: tuple[DeviceConfig, ...], today: date) -> RuntimeState:
        return cls({device.name: RuntimeEntry.for_today(device.name, today) for device in devices})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeState:
        entries = {
            entry.device_name: entry
            for entry in (RuntimeEntry.from_dict(item) for item in data.get("entries", []))
        }
        return cls(entries)

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [entry.to_dict() for entry in self.entries.values()]}

    def get(self, device: DeviceConfig, now: datetime) -> RuntimeEntry:
        entry = self.entries.get(device.name)
        if entry is None:
            entry = RuntimeEntry.for_today(device.name, now.date())
            self.entries[device.name] = entry
        normalized = entry.normalized_for(now.date())
        if normalized is not entry:
            self.entries[device.name] = normalized
        return normalized

    def sync_device_state(self, device: DeviceConfig, is_on: bool, now: datetime) -> RuntimeEntry:
        entry = self.get(device, now)
        if is_on and entry.last_started_at is None:
            entry.last_started_at = now
            return entry
        if not is_on and entry.last_started_at is not None:
            entry.runtime_today_minutes += elapsed_minutes(entry.last_started_at, now)
            entry.last_started_at = None
            entry.last_stopped_at = now
        return entry

    def sync_device_states(
        self,
        devices: tuple[DeviceConfig, ...],
        device_states: dict[str, bool],
        now: datetime,
    ) -> None:
        for device in devices:
            self.sync_device_state(device, device_states.get(device.entity_id, False), now)


def load_runtime_state(path: str | Path) -> RuntimeState:
    runtime_path = Path(path)
    if not runtime_path.exists():
        return RuntimeState()
    with runtime_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return RuntimeState()
    return RuntimeState.from_dict(data)


def save_runtime_state(path: str | Path, state: RuntimeState) -> None:
    runtime_path = Path(path)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    with runtime_path.open("w", encoding="utf-8") as handle:
        json.dump(state.to_dict(), handle, indent=2)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def _format_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
