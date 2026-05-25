import unittest
from datetime import datetime, timedelta

from app.config_store import validate_config_dict
from app.decision_engine import build_device_decisions
from app.diagnostics import EnergySnapshot
from app.runtime_tracker import RuntimeEntry, RuntimeState
from tests.test_config_store import valid_config


def snapshot(
    *,
    available_surplus_w: float = 0,
    solar_surplus_risk_w: float = 0,
    grid_import_w: float = 0,
    battery_soc_percent: float | None = 80,
) -> EnergySnapshot:
    return EnergySnapshot(
        grid_import_w=grid_import_w,
        grid_export_w=available_surplus_w,
        solar_input_w=1200,
        solar_output_w=800,
        battery_soc_percent=battery_soc_percent,
        battery_power_w=0,
        available_surplus_w=available_surplus_w,
        solar_input_above_limit_w=solar_surplus_risk_w,
        solar_surplus_risk_w=solar_surplus_risk_w,
        battery_near_target=solar_surplus_risk_w > 0,
        warnings=(),
    )


def config_with_dehumidifier():
    data = valid_config()
    data["devices"].append(
        {
            "name": "dehumidifier",
            "display_name": "Entfeuchter",
            "entity_id": "switch.dehumidifier",
            "type": "switch",
            "enabled": True,
            "power_w": 300,
            "priority": 20,
            "min_run_minutes": 20,
            "min_off_minutes": 20,
            "min_daily_runtime_minutes": 0,
            "max_daily_runtime_minutes": 180,
            "preferred_window": {"start": "10:00", "end": "20:00"},
            "min_solar_coverage_percent": 80,
            "force_complete_daily_runtime": False,
            "battery_min_soc_percent": 65,
        }
    )
    return validate_config_dict(data)


class DecisionEngineTests(unittest.TestCase):
    def test_turns_pool_pump_on_when_surplus_covers_threshold(self) -> None:
        config = validate_config_dict(valid_config())
        decisions = build_device_decisions(
            config=config,
            snapshot=snapshot(available_surplus_w=400),
            runtime_state=RuntimeState.empty_for_devices(config.enabled_devices, datetime(2026, 5, 25).date()),
            device_states={"switch.pool_pump": False},
            now=datetime(2026, 5, 25, 9, 5),
        )

        self.assertEqual(decisions[0].action, "turn_on")
        self.assertIn("coverage", decisions[0].reason)

    def test_keeps_pool_pump_off_when_battery_too_low(self) -> None:
        config = validate_config_dict(valid_config())
        decisions = build_device_decisions(
            config=config,
            snapshot=snapshot(available_surplus_w=400, battery_soc_percent=40),
            runtime_state=RuntimeState.empty_for_devices(config.enabled_devices, datetime(2026, 5, 25).date()),
            device_states={"switch.pool_pump": False},
            now=datetime(2026, 5, 25, 9, 5),
        )

        self.assertEqual(decisions[0].action, "keep_off")
        self.assertIn("battery", decisions[0].reason)

    def test_forces_pool_pump_when_daily_window_is_tight(self) -> None:
        config = validate_config_dict(valid_config())
        decisions = build_device_decisions(
            config=config,
            snapshot=snapshot(available_surplus_w=0, battery_soc_percent=80),
            runtime_state=RuntimeState.empty_for_devices(config.enabled_devices, datetime(2026, 5, 25).date()),
            device_states={"switch.pool_pump": False},
            now=datetime(2026, 5, 25, 10, 0),
        )

        self.assertEqual(decisions[0].action, "turn_on")
        self.assertIn("daily minimum", decisions[0].reason)

    def test_running_device_respects_min_run(self) -> None:
        config = validate_config_dict(valid_config())
        now = datetime(2026, 5, 25, 12, 10)
        runtime = RuntimeState(
            {
                "pool_pump": RuntimeEntry(
                    device_name="pool_pump",
                    day="2026-05-25",
                    runtime_today_minutes=0,
                    last_started_at=now - timedelta(minutes=10),
                )
            }
        )

        decisions = build_device_decisions(
            config=config,
            snapshot=snapshot(grid_import_w=500),
            runtime_state=runtime,
            device_states={"switch.pool_pump": True},
            now=now,
        )

        self.assertEqual(decisions[0].action, "keep_on")
        self.assertIn("minimum run", decisions[0].reason)

    def test_dehumidifier_only_runs_with_surplus(self) -> None:
        config = config_with_dehumidifier()
        state = RuntimeState.empty_for_devices(config.enabled_devices, datetime(2026, 5, 25).date())

        low = build_device_decisions(
            config=config,
            snapshot=snapshot(available_surplus_w=100, battery_soc_percent=80),
            runtime_state=state,
            device_states={"switch.pool_pump": False, "switch.dehumidifier": False},
            now=datetime(2026, 5, 25, 12, 0),
        )
        high = build_device_decisions(
            config=config,
            snapshot=snapshot(available_surplus_w=300, battery_soc_percent=80),
            runtime_state=state,
            device_states={"switch.pool_pump": False, "switch.dehumidifier": False},
            now=datetime(2026, 5, 25, 12, 0),
        )

        self.assertEqual(low[1].action, "keep_off")
        self.assertEqual(high[1].action, "turn_on")


if __name__ == "__main__":
    unittest.main()
