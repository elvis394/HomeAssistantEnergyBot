from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.diagnostics import EnergySnapshot
from app.models import DeviceConfig, EnergyBotConfig
from app.runtime_tracker import RuntimeState, is_within_window, minutes_until_window_end


DecisionAction = Literal["turn_on", "turn_off", "keep_on", "keep_off", "no_action"]


@dataclass(frozen=True)
class DeviceDecision:
    device_name: str
    entity_id: str
    action: DecisionAction
    reason: str
    effective_surplus_w: float
    solar_coverage_percent: float
    runtime_today_minutes: int


def build_device_decisions(
    config: EnergyBotConfig,
    snapshot: EnergySnapshot,
    runtime_state: RuntimeState,
    device_states: dict[str, bool],
    now: datetime,
) -> tuple[DeviceDecision, ...]:
    decisions: list[DeviceDecision] = []
    for device in sorted(config.enabled_devices, key=lambda item: item.priority):
        is_on = device_states.get(device.entity_id, False)
        decisions.append(_decide_device(config, snapshot, runtime_state, device, is_on, now))
    return tuple(decisions)


def _decide_device(
    config: EnergyBotConfig,
    snapshot: EnergySnapshot,
    runtime_state: RuntimeState,
    device: DeviceConfig,
    is_on: bool,
    now: datetime,
) -> DeviceDecision:
    runtime = runtime_state.get(device, now)
    runtime_today = runtime.runtime_with_current_session(is_on, now)
    remaining_required = max(0, device.min_daily_runtime_minutes - runtime_today)
    remaining_window = minutes_until_window_end(device.preferred_window, now)
    in_window = is_within_window(device.preferred_window, now)
    must_run_for_daily_target = (
        device.force_complete_daily_runtime
        and remaining_required > 0
        and in_window
        and remaining_window <= remaining_required
    )

    effective_surplus_w = max(snapshot.available_surplus_w, snapshot.solar_surplus_risk_w)
    solar_coverage_percent = min(100.0, (effective_surplus_w / device.power_w) * 100)
    required_covered_w = device.power_w * (device.min_solar_coverage_percent / 100)
    has_energy_coverage = effective_surplus_w >= required_covered_w
    battery_too_low = (
        snapshot.battery_soc_percent is not None
        and snapshot.battery_soc_percent < device.battery_min_soc_percent
    )

    if is_on:
        return _decide_running_device(
            config=config,
            snapshot=snapshot,
            device=device,
            runtime_today=runtime_today,
            runtime_has_met_min_run=runtime.has_met_min_run(device, is_on, now),
            in_window=in_window,
            must_run_for_daily_target=must_run_for_daily_target,
            effective_surplus_w=effective_surplus_w,
            solar_coverage_percent=solar_coverage_percent,
        )

    if not in_window:
        return _decision(
            device,
            "keep_off",
            "outside configured time window",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )
    if runtime_today >= device.max_daily_runtime_minutes:
        return _decision(
            device,
            "keep_off",
            "daily maximum runtime already reached",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )
    if not runtime.has_met_min_off(device, now):
        return _decision(
            device,
            "keep_off",
            "minimum off time is still active",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )
    if battery_too_low and not must_run_for_daily_target:
        return _decision(
            device,
            "keep_off",
            "battery SOC is below device minimum",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )
    if must_run_for_daily_target:
        return _decision(
            device,
            "turn_on",
            "daily minimum runtime would otherwise be missed",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )
    if has_energy_coverage:
        return _decision(
            device,
            "turn_on",
            "configured solar coverage is available",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )
    return _decision(
        device,
        "keep_off",
        "not enough covered surplus for this device",
        effective_surplus_w,
        solar_coverage_percent,
        runtime_today,
    )


def _decide_running_device(
    config: EnergyBotConfig,
    snapshot: EnergySnapshot,
    device: DeviceConfig,
    runtime_today: int,
    runtime_has_met_min_run: bool,
    in_window: bool,
    must_run_for_daily_target: bool,
    effective_surplus_w: float,
    solar_coverage_percent: float,
) -> DeviceDecision:
    if not runtime_has_met_min_run:
        return _decision(
            device,
            "keep_on",
            "minimum run time is still active",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )
    if runtime_today >= device.max_daily_runtime_minutes:
        return _decision(
            device,
            "turn_off",
            "daily maximum runtime reached",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )
    if must_run_for_daily_target:
        return _decision(
            device,
            "keep_on",
            "daily minimum runtime still needs this device",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )
    if not in_window:
        return _decision(
            device,
            "turn_off",
            "outside configured time window",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )

    allowed_import_w = device.power_w * ((100 - device.min_solar_coverage_percent) / 100)
    if snapshot.grid_import_w > allowed_import_w:
        return _decision(
            device,
            "turn_off",
            "grid import is above the configured allowance",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )

    if snapshot.battery_soc_percent is not None and snapshot.battery_soc_percent < config.battery.minimum_soc_percent:
        return _decision(
            device,
            "turn_off",
            "battery SOC is below global minimum",
            effective_surplus_w,
            solar_coverage_percent,
            runtime_today,
        )

    return _decision(
        device,
        "keep_on",
        "device is still allowed to run",
        effective_surplus_w,
        solar_coverage_percent,
        runtime_today,
    )


def _decision(
    device: DeviceConfig,
    action: DecisionAction,
    reason: str,
    effective_surplus_w: float,
    solar_coverage_percent: float,
    runtime_today_minutes: int,
) -> DeviceDecision:
    return DeviceDecision(
        device_name=device.name,
        entity_id=device.entity_id,
        action=action,
        reason=reason,
        effective_surplus_w=effective_surplus_w,
        solar_coverage_percent=solar_coverage_percent,
        runtime_today_minutes=runtime_today_minutes,
    )
