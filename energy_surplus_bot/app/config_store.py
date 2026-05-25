from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import ConfigError, EnergyBotConfig


def _load_yaml_with_pyyaml(path: Path) -> Any:
    try:
        import yaml  # type: ignore[import-untyped]
    except ModuleNotFoundError as exc:
        return _load_limited_yaml(path, exc)

    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _load_limited_yaml(path: Path, original_error: ModuleNotFoundError) -> Any:
    """Parse the small YAML subset used by config.example.yaml in dependency-free dev runs."""

    parsed_lines: list[tuple[int, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if "\t" in raw_line:
                raise ConfigError(f"{path}:{line_number} uses tabs; use spaces for indentation") from original_error
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            parsed_lines.append((indent, stripped))

    def parse_scalar(value: str) -> Any:
        value = value.strip()
        if not value:
            return None
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
        if value == "true":
            return True
        if value == "false":
            return False
        if value == "null":
            return None
        try:
            return int(value)
        except ValueError:
            return value

    def split_key_value(text: str) -> tuple[str, str | None]:
        if ":" not in text:
            raise ConfigError(f"Invalid YAML line in {path}: {text}") from original_error
        key, value = text.split(":", 1)
        key = key.strip()
        if not key:
            raise ConfigError(f"Invalid YAML key in {path}: {text}") from original_error
        value = value.strip()
        return key, value if value else None

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(parsed_lines):
            return {}, index
        current_indent, current_text = parsed_lines[index]
        if current_indent < indent:
            return {}, index
        if current_indent > indent:
            raise ConfigError(f"Unexpected indentation in {path}: {current_text}") from original_error

        if current_text.startswith("- "):
            items: list[Any] = []
            while index < len(parsed_lines):
                line_indent, text = parsed_lines[index]
                if line_indent < indent:
                    break
                if line_indent != indent or not text.startswith("- "):
                    break

                rest = text[2:].strip()
                index += 1
                if not rest:
                    item, index = parse_block(index, indent + 2)
                    items.append(item)
                elif ":" in rest:
                    key, value = split_key_value(rest)
                    item: dict[str, Any] = {}
                    if value is None:
                        child, index = parse_block(index, indent + 2)
                        item[key] = child
                    else:
                        item[key] = parse_scalar(value)
                    if index < len(parsed_lines) and parsed_lines[index][0] == indent + 2:
                        child, index = parse_block(index, indent + 2)
                        if not isinstance(child, dict):
                            raise ConfigError(f"Expected mapping under list item in {path}") from original_error
                        item.update(child)
                    items.append(item)
                else:
                    items.append(parse_scalar(rest))
            return items, index

        mapping: dict[str, Any] = {}
        while index < len(parsed_lines):
            line_indent, text = parsed_lines[index]
            if line_indent < indent:
                break
            if line_indent != indent:
                raise ConfigError(f"Unexpected indentation in {path}: {text}") from original_error
            if text.startswith("- "):
                break

            key, value = split_key_value(text)
            index += 1
            if value is None:
                child, index = parse_block(index, indent + 2)
                mapping[key] = child
            else:
                mapping[key] = parse_scalar(value)
        return mapping, index

    result, final_index = parse_block(0, 0)
    if final_index != len(parsed_lines):
        raise ConfigError(f"Could not fully parse YAML file: {path}") from original_error
    return result


def load_raw_config(path: str | Path) -> Any:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    suffix = config_path.suffix.lower()
    if suffix == ".json":
        with config_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    if suffix in {".yaml", ".yml"}:
        return _load_yaml_with_pyyaml(config_path)
    raise ConfigError(f"Unsupported config format: {config_path.suffix}")


def load_config(path: str | Path) -> EnergyBotConfig:
    return EnergyBotConfig.from_dict(load_raw_config(path))


def validate_config_dict(data: dict[str, Any]) -> EnergyBotConfig:
    return EnergyBotConfig.from_dict(data)
