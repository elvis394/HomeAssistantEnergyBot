from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


class ConfigError(ValueError):
    """Raised when the application configuration is invalid."""


def _require_mapping(data: Any, path: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be an object")
    return data


def _require_list(data: Any, path: str) -> list[Any]:
    if not isinstance(data, list):
        raise ConfigError(f"{path} must be a list")
    return data


def _require_str(data: dict[str, Any], key: str, path: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def _bool(data: dict[str, Any], key: str, path: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{path}.{key} must be a boolean")
    return value


def _int_range(
    data: dict[str, Any],
    key: str,
    path: str,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{path}.{key} must be an integer")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{path}.{key} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{path}.{key} must be at most {maximum}")
    return value


def _time_value(data: dict[str, Any], key: str, path: str) -> str:
    value = _require_str(data, key, path)
    parts = value.split(":")
    if len(parts) != 2:
        raise ConfigError(f"{path}.{key} must use HH:MM format")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ConfigError(f"{path}.{key} must use HH:MM format") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ConfigError(f"{path}.{key} must be a valid time")
    return f"{hour:02d}:{minute:02d}"


@dataclass(frozen=True)
class AppSettings:
    auto_mode: bool
    dry_run: bool
    decision_interval_seconds: int
    smoothing_window_minutes: int
    reserve_w: int

    @classmethod
    def from_dict(cls, data: Any) -> AppSettings:
        mapping = _require_mapping(data, "app")
        return cls(
            auto_mode=_bool(mapping, "auto_mode", "app", default=False),
            dry_run=_bool(mapping, "dry_run", "app", default=True),
            decision_interval_seconds=_int_range(
                mapping, "decision_interval_seconds", "app", default=30, minimum=5
            ),
            smoothing_window_minutes=_int_range(
                mapping, "smoothing_window_minutes", "app", default=5, minimum=1
            ),
            reserve_w=_int_range(mapping, "reserve_w", "app", default=150, minimum=0),
        )


@dataclass(frozen=True)
class HomeAssistantSettings:
    url: str
    token_env: str

    @classmethod
    def from_dict(cls, data: Any) -> HomeAssistantSettings:
        mapping = _require_mapping(data, "home_assistant")
        return cls(
            url=_require_str(mapping, "url", "home_assistant"),
            token_env=_require_str(mapping, "token_env", "home_assistant"),
        )


@dataclass(frozen=True)
class AnkerSystemConfig:
    name: str
    solar_input_power_entity: str
    solar_output_power_entity: str
    battery_soc_entity: str
    battery_power_entity: str

    @classmethod
    def from_dict(cls, data: Any, index: int) -> AnkerSystemConfig:
        path = f"sources.anker_systems[{index}]"
        mapping = _require_mapping(data, path)
        return cls(
            name=_require_str(mapping, "name", path),
            solar_input_power_entity=_require_str(mapping, "solar_input_power_entity", path),
            solar_output_power_entity=_require_str(mapping, "solar_output_power_entity", path),
            battery_soc_entity=_require_str(mapping, "battery_soc_entity", path),
            battery_power_entity=_require_str(mapping, "battery_power_entity", path),
        )


@dataclass(frozen=True)
class SourceSettings:
    grid_import_power_entity: str
    grid_export_power_entity: str
    solarbox_output_limit_w: int
    anker_systems: tuple[AnkerSystemConfig, ...]

    @classmethod
    def from_dict(cls, data: Any) -> SourceSettings:
        mapping = _require_mapping(data, "sources")
        systems = tuple(
            AnkerSystemConfig.from_dict(item, index)
            for index, item in enumerate(_require_list(mapping.get("anker_systems"), "sources.anker_systems"))
        )
        if not systems:
            raise ConfigError("sources.anker_systems must contain at least one system")
        return cls(
            grid_import_power_entity=_require_str(mapping, "grid_import_power_entity", "sources"),
            grid_export_power_entity=_require_str(mapping, "grid_export_power_entity", "sources"),
            solarbox_output_limit_w=_int_range(
                mapping, "solarbox_output_limit_w", "sources", default=800, minimum=1
            ),
            anker_systems=systems,
        )


@dataclass(frozen=True)
class BatterySettings:
    target_soc_percent: int
    minimum_soc_percent: int
    near_target_margin_percent: int
    soc_aggregation: Literal["min", "average"]
    over_target_action: Literal["prefer_consumers", "hold"]

    @classmethod
    def from_dict(cls, data: Any) -> BatterySettings:
        mapping = _require_mapping(data, "battery")
        target = _int_range(mapping, "target_soc_percent", "battery", default=80, minimum=1, maximum=100)
        minimum = _int_range(mapping, "minimum_soc_percent", "battery", default=30, minimum=0, maximum=100)
        if minimum >= target:
            raise ConfigError("battery.minimum_soc_percent must be lower than battery.target_soc_percent")

        soc_aggregation = mapping.get("soc_aggregation", "min")
        if soc_aggregation not in {"min", "average"}:
            raise ConfigError("battery.soc_aggregation must be 'min' or 'average'")

        over_target_action = mapping.get("over_target_action", "prefer_consumers")
        if over_target_action not in {"prefer_consumers", "hold"}:
            raise ConfigError("battery.over_target_action must be 'prefer_consumers' or 'hold'")

        return cls(
            target_soc_percent=target,
            minimum_soc_percent=minimum,
            near_target_margin_percent=_int_range(
                mapping, "near_target_margin_percent", "battery", default=5, minimum=0, maximum=50
            ),
            soc_aggregation=soc_aggregation,
            over_target_action=over_target_action,
        )


@dataclass(frozen=True)
class TimeWindow:
    start: str
    end: str

    @classmethod
    def from_dict(cls, data: Any, path: str) -> TimeWindow:
        mapping = _require_mapping(data, path)
        return cls(
            start=_time_value(mapping, "start", path),
            end=_time_value(mapping, "end", path),
        )


@dataclass(frozen=True)
class DeviceConfig:
    name: str
    display_name: str
    entity_id: str
    type: Literal["switch"]
    enabled: bool
    power_w: int
    priority: int
    min_run_minutes: int
    min_off_minutes: int
    min_daily_runtime_minutes: int
    max_daily_runtime_minutes: int
    preferred_window: TimeWindow
    min_solar_coverage_percent: int
    force_complete_daily_runtime: bool
    battery_min_soc_percent: int

    @classmethod
    def from_dict(cls, data: Any, index: int) -> DeviceConfig:
        path = f"devices[{index}]"
        mapping = _require_mapping(data, path)
        device_type = mapping.get("type", "switch")
        if device_type != "switch":
            raise ConfigError(f"{path}.type must be 'switch'")

        min_daily = _int_range(mapping, "min_daily_runtime_minutes", path, default=0, minimum=0)
        max_daily = _int_range(mapping, "max_daily_runtime_minutes", path, default=1440, minimum=0)
        if max_daily and max_daily < min_daily:
            raise ConfigError(f"{path}.max_daily_runtime_minutes must be greater than or equal to min_daily_runtime_minutes")

        return cls(
            name=_require_str(mapping, "name", path),
            display_name=_require_str(mapping, "display_name", path),
            entity_id=_require_str(mapping, "entity_id", path),
            type=device_type,
            enabled=_bool(mapping, "enabled", path, default=True),
            power_w=_int_range(mapping, "power_w", path, minimum=1),
            priority=_int_range(mapping, "priority", path, default=100, minimum=0),
            min_run_minutes=_int_range(mapping, "min_run_minutes", path, default=0, minimum=0),
            min_off_minutes=_int_range(mapping, "min_off_minutes", path, default=0, minimum=0),
            min_daily_runtime_minutes=min_daily,
            max_daily_runtime_minutes=max_daily,
            preferred_window=TimeWindow.from_dict(mapping.get("preferred_window"), f"{path}.preferred_window"),
            min_solar_coverage_percent=_int_range(
                mapping, "min_solar_coverage_percent", path, default=100, minimum=0, maximum=100
            ),
            force_complete_daily_runtime=_bool(mapping, "force_complete_daily_runtime", path, default=False),
            battery_min_soc_percent=_int_range(
                mapping, "battery_min_soc_percent", path, default=0, minimum=0, maximum=100
            ),
        )


@dataclass(frozen=True)
class UiSettings:
    enabled: bool
    host: str
    port: int
    allow_entity_picker: bool
    config_path: str

    @classmethod
    def from_dict(cls, data: Any) -> UiSettings:
        mapping = _require_mapping(data, "ui")
        return cls(
            enabled=_bool(mapping, "enabled", "ui", default=True),
            host=_require_str(mapping, "host", "ui"),
            port=_int_range(mapping, "port", "ui", default=8099, minimum=1, maximum=65535),
            allow_entity_picker=_bool(mapping, "allow_entity_picker", "ui", default=True),
            config_path=_require_str(mapping, "config_path", "ui"),
        )


@dataclass(frozen=True)
class EnergyBotConfig:
    app: AppSettings
    home_assistant: HomeAssistantSettings
    sources: SourceSettings
    battery: BatterySettings
    devices: tuple[DeviceConfig, ...]
    ui: UiSettings

    @classmethod
    def from_dict(cls, data: Any) -> EnergyBotConfig:
        mapping = _require_mapping(data, "config")
        devices = tuple(
            DeviceConfig.from_dict(item, index)
            for index, item in enumerate(_require_list(mapping.get("devices"), "devices"))
        )
        if not devices:
            raise ConfigError("devices must contain at least one device")
        return cls(
            app=AppSettings.from_dict(mapping.get("app")),
            home_assistant=HomeAssistantSettings.from_dict(mapping.get("home_assistant")),
            sources=SourceSettings.from_dict(mapping.get("sources")),
            battery=BatterySettings.from_dict(mapping.get("battery")),
            devices=devices,
            ui=UiSettings.from_dict(mapping.get("ui")),
        )

    @property
    def enabled_devices(self) -> tuple[DeviceConfig, ...]:
        return tuple(device for device in self.devices if device.enabled)
