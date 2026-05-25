from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.models import EnergyBotConfig


class HomeAssistantError(RuntimeError):
    """Raised when Home Assistant cannot be reached or returns invalid data."""


@dataclass(frozen=True)
class EntityState:
    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: str | None = None
    last_updated: str | None = None


def state_to_float(state: EntityState) -> float | None:
    value = state.state.strip()
    if value.lower() in {"unknown", "unavailable", "none", ""}:
        return None
    value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, config: EnergyBotConfig) -> HomeAssistantClient:
        token = read_token(config.home_assistant.token_env)
        if not token:
            raise HomeAssistantError(
                f"Token {config.home_assistant.token_env} is required for Home Assistant access. "
                "Make sure the add-on has homeassistant_api enabled and was restarted after updating."
            )
        return cls(config.home_assistant.url, token)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = response.read().decode("utf-8")
                return json.loads(data) if data else None
        except HTTPError as exc:
            raise HomeAssistantError(f"Home Assistant returned HTTP {exc.code} for {path}") from exc
        except URLError as exc:
            raise HomeAssistantError(f"Could not reach Home Assistant at {self.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise HomeAssistantError(f"Home Assistant returned invalid JSON for {path}") from exc

    @staticmethod
    def _parse_state(data: dict[str, Any]) -> EntityState:
        return EntityState(
            entity_id=str(data.get("entity_id", "")),
            state=str(data.get("state", "")),
            attributes=dict(data.get("attributes") or {}),
            last_changed=data.get("last_changed"),
            last_updated=data.get("last_updated"),
        )

    def list_states(self) -> list[EntityState]:
        data = self._request("GET", "/api/states")
        if not isinstance(data, list):
            raise HomeAssistantError("Home Assistant /api/states did not return a list")
        return [self._parse_state(item) for item in data if isinstance(item, dict)]

    def get_state(self, entity_id: str) -> EntityState:
        encoded_id = quote(entity_id, safe="")
        data = self._request("GET", f"/api/states/{encoded_id}")
        if not isinstance(data, dict):
            raise HomeAssistantError(f"Home Assistant state for {entity_id} is not an object")
        state = self._parse_state(data)
        if not state.entity_id:
            return EntityState(entity_id=entity_id, state=state.state, attributes=state.attributes)
        return state

    def get_numeric_state(self, entity_id: str) -> float | None:
        return state_to_float(self.get_state(entity_id))

    def call_service(self, domain: str, service: str, entity_id: str, dry_run: bool = True) -> dict[str, Any]:
        payload = {"entity_id": entity_id}
        if dry_run:
            return {
                "dry_run": True,
                "domain": domain,
                "service": service,
                "payload": payload,
            }
        result = self._request("POST", f"/api/services/{domain}/{service}", payload)
        return {
            "dry_run": False,
            "domain": domain,
            "service": service,
            "payload": payload,
            "result": result,
        }


class DemoHomeAssistantClient:
    def __init__(self, states: dict[str, EntityState]) -> None:
        self.states = states
        self.service_calls: list[dict[str, Any]] = []

    @classmethod
    def from_config(cls, config: EnergyBotConfig) -> DemoHomeAssistantClient:
        states: dict[str, EntityState] = {
            config.sources.grid_import_power_entity: EntityState(
                config.sources.grid_import_power_entity, "0", {"unit_of_measurement": "W"}
            ),
            config.sources.grid_export_power_entity: EntityState(
                config.sources.grid_export_power_entity, "420", {"unit_of_measurement": "W"}
            ),
        }
        if config.sources.house_power_entity:
            states[config.sources.house_power_entity] = EntityState(
                config.sources.house_power_entity, "680", {"unit_of_measurement": "W"}
            )

        for index, system in enumerate(config.sources.anker_systems, start=1):
            states[system.solar_input_power_entity] = EntityState(
                system.solar_input_power_entity, str(850 - index * 50), {"unit_of_measurement": "W"}
            )
            states[system.solar_output_power_entity] = EntityState(
                system.solar_output_power_entity, str(360 + index * 20), {"unit_of_measurement": "W"}
            )
            states[system.battery_soc_entity] = EntityState(
                system.battery_soc_entity, str(79 - index), {"unit_of_measurement": "%"}
            )
            states[system.battery_power_entity] = EntityState(
                system.battery_power_entity, str(120 + index * 30), {"unit_of_measurement": "W"}
            )

        for device in config.devices:
            states[device.entity_id] = EntityState(device.entity_id, "off", {})

        return cls(states)

    def list_states(self) -> list[EntityState]:
        return [self.states[key] for key in sorted(self.states)]

    def get_state(self, entity_id: str) -> EntityState:
        try:
            return self.states[entity_id]
        except KeyError as exc:
            raise HomeAssistantError(f"Demo state not found: {entity_id}") from exc

    def get_numeric_state(self, entity_id: str) -> float | None:
        return state_to_float(self.get_state(entity_id))

    def call_service(self, domain: str, service: str, entity_id: str, dry_run: bool = True) -> dict[str, Any]:
        call = {
            "dry_run": dry_run,
            "domain": domain,
            "service": service,
            "payload": {"entity_id": entity_id},
        }
        self.service_calls.append(call)
        return call


def read_token(name: str) -> str | None:
    candidates = [name]
    if name == "SUPERVISOR_TOKEN":
        candidates.append("HASSIO_TOKEN")

    for candidate in candidates:
        value = os.environ.get(candidate)
        if value:
            return value

    for candidate in candidates:
        value = _read_env_file(candidate)
        if value:
            return value
    return None


def _read_env_file(name: str) -> str | None:
    for base_path in (
        Path("/run/s6/container_environment"),
        Path("/var/run/s6/container_environment"),
    ):
        token_path = base_path / name
        try:
            value = token_path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None
