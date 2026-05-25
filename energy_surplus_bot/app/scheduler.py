from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.decision_engine import DeviceDecision, build_device_decisions
from app.diagnostics import EnergySnapshot, build_energy_snapshot
from app.ha_client import EntityState, HomeAssistantError
from app.models import EnergyBotConfig
from app.runtime_tracker import RuntimeState, load_runtime_state, save_runtime_state


class EnergyBotClient(Protocol):
    def get_state(self, entity_id: str) -> EntityState:
        ...

    def get_numeric_state(self, entity_id: str) -> float | None:
        ...

    def call_service(self, domain: str, service: str, entity_id: str, dry_run: bool = True) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ServiceCallResult:
    device_name: str
    entity_id: str
    action: str
    skipped: bool
    reason: str
    response: dict[str, Any] | None = None


@dataclass(frozen=True)
class SchedulerResult:
    snapshot: EnergySnapshot
    decisions: tuple[DeviceDecision, ...]
    service_calls: tuple[ServiceCallResult, ...]
    device_states: dict[str, bool]
    ran_at: datetime


def read_device_states(config: EnergyBotConfig, client: EnergyBotClient) -> dict[str, bool]:
    states: dict[str, bool] = {}
    for device in config.enabled_devices:
        try:
            states[device.entity_id] = client.get_state(device.entity_id).state.lower() == "on"
        except HomeAssistantError:
            states[device.entity_id] = False
    return states


def run_once(
    config: EnergyBotConfig,
    client: EnergyBotClient,
    runtime_state: RuntimeState,
    now: datetime | None = None,
) -> SchedulerResult:
    current_time = now or datetime.now()
    device_states = read_device_states(config, client)
    runtime_state.sync_device_states(config.enabled_devices, device_states, current_time)
    snapshot = build_energy_snapshot(config, client)
    decisions = build_device_decisions(config, snapshot, runtime_state, device_states, current_time)
    service_calls = tuple(_apply_decision(config, client, decision) for decision in decisions)
    return SchedulerResult(
        snapshot=snapshot,
        decisions=decisions,
        service_calls=service_calls,
        device_states=device_states,
        ran_at=current_time,
    )


def run_loop(
    config: EnergyBotConfig,
    client: EnergyBotClient,
    runtime_path: str | Path,
    stop_after_ticks: int | None = None,
) -> None:
    runtime_state = load_runtime_state(runtime_path)
    ticks = 0
    while True:
        result = run_once(config, client, runtime_state)
        save_runtime_state(runtime_path, runtime_state)
        _print_result(result)
        ticks += 1
        if stop_after_ticks is not None and ticks >= stop_after_ticks:
            return
        time.sleep(config.app.decision_interval_seconds)


def _apply_decision(
    config: EnergyBotConfig,
    client: EnergyBotClient,
    decision: DeviceDecision,
) -> ServiceCallResult:
    if decision.action not in {"turn_on", "turn_off"}:
        return ServiceCallResult(
            device_name=decision.device_name,
            entity_id=decision.entity_id,
            action=decision.action,
            skipped=True,
            reason="decision does not require a service call",
        )
    if not config.app.auto_mode:
        return ServiceCallResult(
            device_name=decision.device_name,
            entity_id=decision.entity_id,
            action=decision.action,
            skipped=True,
            reason="auto_mode is disabled",
        )

    service = "turn_on" if decision.action == "turn_on" else "turn_off"
    response = client.call_service("switch", service, decision.entity_id, dry_run=config.app.dry_run)
    return ServiceCallResult(
        device_name=decision.device_name,
        entity_id=decision.entity_id,
        action=decision.action,
        skipped=False,
        reason="service call executed" if not config.app.dry_run else "dry-run service call recorded",
        response=response,
    )


def _print_result(result: SchedulerResult) -> None:
    print(f"Energy Bot tick at {result.ran_at.isoformat(timespec='seconds')}")
    for line in result.snapshot.as_lines():
        print(f"- {line}")
    for decision in result.decisions:
        print(f"- {decision.device_name}: {decision.action} ({decision.reason})")
