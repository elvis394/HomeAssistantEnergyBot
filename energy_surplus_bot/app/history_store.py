from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.scheduler import SchedulerResult


@dataclass(frozen=True)
class HistoryEntry:
    ran_at: str
    grid_import_w: float
    grid_export_w: float
    house_power_w: float
    solar_input_w: float
    solar_output_w: float
    battery_soc_percent: float | None
    available_surplus_w: float
    solar_surplus_risk_w: float
    decisions: tuple[str, ...]
    service_calls: tuple[str, ...]

    @classmethod
    def from_scheduler_result(cls, result: SchedulerResult) -> HistoryEntry:
        return cls(
            ran_at=result.ran_at.isoformat(),
            grid_import_w=result.snapshot.grid_import_w,
            grid_export_w=result.snapshot.grid_export_w,
            house_power_w=result.snapshot.house_power_w,
            solar_input_w=result.snapshot.solar_input_w,
            solar_output_w=result.snapshot.solar_output_w,
            battery_soc_percent=result.snapshot.battery_soc_percent,
            available_surplus_w=result.snapshot.available_surplus_w,
            solar_surplus_risk_w=result.snapshot.solar_surplus_risk_w,
            decisions=tuple(f"{item.device_name}: {item.action} ({item.reason})" for item in result.decisions),
            service_calls=tuple(
                f"{item.device_name}: {'skipped' if item.skipped else 'sent'} ({item.reason})"
                for item in result.service_calls
            ),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        return cls(
            ran_at=str(data.get("ran_at", "")),
            grid_import_w=float(data.get("grid_import_w", 0)),
            grid_export_w=float(data.get("grid_export_w", 0)),
            house_power_w=float(data.get("house_power_w", 0)),
            solar_input_w=float(data.get("solar_input_w", 0)),
            solar_output_w=float(data.get("solar_output_w", 0)),
            battery_soc_percent=_optional_float(data.get("battery_soc_percent")),
            available_surplus_w=float(data.get("available_surplus_w", 0)),
            solar_surplus_risk_w=float(data.get("solar_surplus_risk_w", 0)),
            decisions=tuple(str(item) for item in data.get("decisions", [])),
            service_calls=tuple(str(item) for item in data.get("service_calls", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran_at": self.ran_at,
            "grid_import_w": self.grid_import_w,
            "grid_export_w": self.grid_export_w,
            "house_power_w": self.house_power_w,
            "solar_input_w": self.solar_input_w,
            "solar_output_w": self.solar_output_w,
            "battery_soc_percent": self.battery_soc_percent,
            "available_surplus_w": self.available_surplus_w,
            "solar_surplus_risk_w": self.solar_surplus_risk_w,
            "decisions": list(self.decisions),
            "service_calls": list(self.service_calls),
        }


@dataclass
class HistoryState:
    entries: list[HistoryEntry]

    @classmethod
    def empty(cls) -> HistoryState:
        return cls(entries=[])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryState:
        return cls(
            entries=[
                HistoryEntry.from_dict(item)
                for item in data.get("entries", [])
                if isinstance(item, dict)
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [entry.to_dict() for entry in self.entries]}

    def append(self, entry: HistoryEntry, limit: int = 200) -> None:
        if self.entries and self.entries[-1].ran_at == entry.ran_at:
            self.entries[-1] = entry
        else:
            self.entries.append(entry)
        if len(self.entries) > limit:
            self.entries = self.entries[-limit:]


def load_history_state(path: str | Path) -> HistoryState:
    history_path = Path(path)
    if not history_path.exists():
        return HistoryState.empty()
    with history_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return HistoryState.empty()
    return HistoryState.from_dict(data)


def save_history_state(path: str | Path, state: HistoryState) -> None:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w", encoding="utf-8") as handle:
        json.dump(state.to_dict(), handle, indent=2)


def append_history_entry(path: str | Path, result: SchedulerResult, limit: int = 200) -> HistoryState:
    state = load_history_state(path)
    state.append(HistoryEntry.from_scheduler_result(result), limit=limit)
    save_history_state(path, state)
    return state


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
