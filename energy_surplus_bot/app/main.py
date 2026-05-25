from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from app.config_store import load_config
from app.ha_client import DemoHomeAssistantClient, HomeAssistantClient, HomeAssistantError
from app.models import ConfigError, EnergyBotConfig
from app.runtime_tracker import load_runtime_state, save_runtime_state
from app.scheduler import run_once
from app.ui.server import serve_ui


def describe_config(config: EnergyBotConfig) -> str:
    anker_count = len(config.sources.anker_systems)
    device_count = len(config.devices)
    enabled_count = len(config.enabled_devices)
    mode = "auto" if config.app.auto_mode else "manual"
    dry_run = "dry-run" if config.app.dry_run else "live"
    return (
        "Energy Bot configuration loaded: "
        f"{anker_count} Anker system(s), {device_count} device(s), "
        f"{enabled_count} enabled, mode={mode}, execution={dry_run}."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Home Assistant Energy Surplus Bot")
    parser.add_argument(
        "--config",
        default=os.environ.get("ENERGY_BOT_CONFIG", "config.example.yaml"),
        help="Path to YAML or JSON configuration file.",
    )
    parser.add_argument(
        "--runtime",
        default=os.environ.get("ENERGY_BOT_RUNTIME", "runtime.json"),
        help="Path to runtime-state JSON file.",
    )
    parser.add_argument(
        "--live-ha",
        action="store_true",
        help="Read values from the configured Home Assistant instead of built-in demo states.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the built-in web UI.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scheduler tick and exit. This is the default when --serve is not set.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = Path(args.config)

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    print(describe_config(config))

    if args.serve:
        serve_ui(
            config_path=config_path,
            runtime_path=Path(args.runtime),
            host=config.ui.host,
            port=config.ui.port,
            use_live_ha=args.live_ha,
        )
        return 0

    try:
        client = HomeAssistantClient.from_config(config) if args.live_ha else DemoHomeAssistantClient.from_config(config)
        runtime_state = load_runtime_state(args.runtime)
        result = run_once(config, client, runtime_state, now=datetime.now())
        save_runtime_state(args.runtime, runtime_state)
    except HomeAssistantError as exc:
        print(f"Home Assistant error: {exc}", file=sys.stderr)
        return 3

    source = "Home Assistant" if args.live_ha else "demo states"
    print(f"Energy snapshot from {source}:")
    for line in result.snapshot.as_lines():
        print(f"- {line}")
    if result.snapshot.warnings:
        print("Warnings:")
        for warning in result.snapshot.warnings:
            print(f"- {warning}")

    print("Dry-run decisions:")
    for decision in result.decisions:
        print(
            f"- {decision.device_name}: {decision.action} "
            f"({decision.reason}, coverage={decision.solar_coverage_percent:.0f}%, "
            f"runtime_today={decision.runtime_today_minutes} min)"
        )
    print("Service calls:")
    for service_call in result.service_calls:
        status = "skipped" if service_call.skipped else "sent"
        print(f"- {service_call.device_name}: {status} ({service_call.reason})")

    print("UI is not started in --once mode. Use --serve to run the add-on web UI and background scheduler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
