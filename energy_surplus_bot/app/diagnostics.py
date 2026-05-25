from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.ha_client import HomeAssistantError
from app.models import EnergyBotConfig


class NumericStateClient(Protocol):
    def get_numeric_state(self, entity_id: str) -> float | None:
        ...


@dataclass(frozen=True)
class EnergySnapshot:
    grid_import_w: float
    grid_export_w: float
    solar_input_w: float
    solar_output_w: float
    battery_soc_percent: float | None
    battery_power_w: float
    available_surplus_w: float
    solar_input_above_limit_w: float
    solar_surplus_risk_w: float
    battery_near_target: bool
    warnings: tuple[str, ...]

    def as_lines(self) -> list[str]:
        soc = "unknown" if self.battery_soc_percent is None else f"{self.battery_soc_percent:.1f}%"
        return [
            f"grid import: {self.grid_import_w:.0f} W",
            f"grid export: {self.grid_export_w:.0f} W",
            f"solar input: {self.solar_input_w:.0f} W",
            f"solar output: {self.solar_output_w:.0f} W",
            f"battery SOC: {soc}",
            f"battery power: {self.battery_power_w:.0f} W",
            f"available surplus after reserve: {self.available_surplus_w:.0f} W",
            f"solar input above output limit: {self.solar_input_above_limit_w:.0f} W",
            f"solar surplus risk: {self.solar_surplus_risk_w:.0f} W",
        ]


def _read_numeric(client: NumericStateClient, entity_id: str, warnings: list[str]) -> float:
    try:
        value = client.get_numeric_state(entity_id)
    except HomeAssistantError as exc:
        warnings.append(f"{entity_id}: {exc}")
        return 0.0
    if value is None:
        warnings.append(f"{entity_id}: state is not numeric")
        return 0.0
    return value


def _read_optional_numeric(client: NumericStateClient, entity_id: str, warnings: list[str]) -> float | None:
    try:
        value = client.get_numeric_state(entity_id)
    except HomeAssistantError as exc:
        warnings.append(f"{entity_id}: {exc}")
        return None
    if value is None:
        warnings.append(f"{entity_id}: state is not numeric")
    return value


def _aggregate_soc(values: list[float], strategy: str) -> float | None:
    if not values:
        return None
    if strategy == "average":
        return sum(values) / len(values)
    return min(values)


def build_energy_snapshot(config: EnergyBotConfig, client: NumericStateClient) -> EnergySnapshot:
    warnings: list[str] = []
    grid_import_w = _read_numeric(client, config.sources.grid_import_power_entity, warnings)
    grid_export_w = _read_numeric(client, config.sources.grid_export_power_entity, warnings)

    solar_input_w = 0.0
    solar_output_w = 0.0
    battery_power_w = 0.0
    soc_values: list[float] = []

    for system in config.sources.anker_systems:
        solar_input_w += _read_numeric(client, system.solar_input_power_entity, warnings)
        solar_output_w += _read_numeric(client, system.solar_output_power_entity, warnings)
        battery_power_w += _read_numeric(client, system.battery_power_entity, warnings)
        soc = _read_optional_numeric(client, system.battery_soc_entity, warnings)
        if soc is not None:
            soc_values.append(soc)

    battery_soc_percent = _aggregate_soc(soc_values, config.battery.soc_aggregation)
    battery_near_target = (
        battery_soc_percent is not None
        and battery_soc_percent >= config.battery.target_soc_percent - config.battery.near_target_margin_percent
    )

    net_export_w = max(0.0, grid_export_w - grid_import_w)
    available_surplus_w = max(0.0, net_export_w - config.app.reserve_w)
    solar_input_above_limit_w = max(0.0, solar_input_w - config.sources.solarbox_output_limit_w)
    solar_surplus_risk_w = solar_input_above_limit_w if battery_near_target else 0.0

    return EnergySnapshot(
        grid_import_w=grid_import_w,
        grid_export_w=grid_export_w,
        solar_input_w=solar_input_w,
        solar_output_w=solar_output_w,
        battery_soc_percent=battery_soc_percent,
        battery_power_w=battery_power_w,
        available_surplus_w=available_surplus_w,
        solar_input_above_limit_w=solar_input_above_limit_w,
        solar_surplus_risk_w=solar_surplus_risk_w,
        battery_near_target=battery_near_target,
        warnings=tuple(warnings),
    )
