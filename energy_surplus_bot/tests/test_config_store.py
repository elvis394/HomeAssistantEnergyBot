import unittest

from app.config_store import validate_config_dict
from app.models import ConfigError


def valid_config() -> dict:
    return {
        "app": {
            "auto_mode": False,
            "dry_run": True,
            "decision_interval_seconds": 30,
            "smoothing_window_minutes": 5,
            "reserve_w": 150,
        },
        "home_assistant": {
            "url": "http://homeassistant.local:8123",
            "token_env": "HA_TOKEN",
        },
        "sources": {
            "grid_import_power_entity": "sensor.grid_import_power",
            "grid_export_power_entity": "sensor.grid_export_power",
            "solarbox_output_limit_w": 800,
            "anker_systems": [
                {
                    "name": "anker_1",
                    "solar_input_power_entity": "sensor.anker_1_solar_input_power",
                    "solar_output_power_entity": "sensor.anker_1_solar_output_power",
                    "battery_soc_entity": "sensor.anker_1_battery_soc",
                    "battery_power_entity": "sensor.anker_1_battery_power",
                },
                {
                    "name": "anker_2",
                    "solar_input_power_entity": "sensor.anker_2_solar_input_power",
                    "solar_output_power_entity": "sensor.anker_2_solar_output_power",
                    "battery_soc_entity": "sensor.anker_2_battery_soc",
                    "battery_power_entity": "sensor.anker_2_battery_power",
                },
            ],
        },
        "battery": {
            "target_soc_percent": 80,
            "minimum_soc_percent": 30,
            "near_target_margin_percent": 5,
            "soc_aggregation": "min",
            "over_target_action": "prefer_consumers",
        },
        "devices": [
            {
                "name": "pool_pump",
                "display_name": "Poolpumpe",
                "entity_id": "switch.pool_pump",
                "type": "switch",
                "enabled": True,
                "power_w": 450,
                "priority": 10,
                "min_run_minutes": 30,
                "min_off_minutes": 20,
                "min_daily_runtime_minutes": 480,
                "max_daily_runtime_minutes": 720,
                "preferred_window": {"start": "09:00", "end": "18:00"},
                "min_solar_coverage_percent": 70,
                "force_complete_daily_runtime": True,
                "battery_min_soc_percent": 55,
            }
        ],
        "ui": {
            "enabled": True,
            "host": "0.0.0.0",
            "port": 8099,
            "allow_entity_picker": True,
            "config_path": "/data/options.json",
        },
    }


class ConfigValidationTests(unittest.TestCase):
    def test_valid_config_loads(self) -> None:
        config = validate_config_dict(valid_config())

        self.assertEqual(config.battery.target_soc_percent, 80)
        self.assertEqual(len(config.sources.anker_systems), 2)
        self.assertEqual(config.devices[0].name, "pool_pump")
        self.assertEqual(config.enabled_devices[0].display_name, "Poolpumpe")

    def test_battery_minimum_must_be_below_target(self) -> None:
        data = valid_config()
        data["battery"]["minimum_soc_percent"] = 80

        with self.assertRaisesRegex(ConfigError, "minimum_soc_percent"):
            validate_config_dict(data)

    def test_device_daily_max_must_cover_daily_min(self) -> None:
        data = valid_config()
        data["devices"][0]["max_daily_runtime_minutes"] = 120

        with self.assertRaisesRegex(ConfigError, "max_daily_runtime_minutes"):
            validate_config_dict(data)

    def test_time_window_must_be_valid(self) -> None:
        data = valid_config()
        data["devices"][0]["preferred_window"]["start"] = "28:15"

        with self.assertRaisesRegex(ConfigError, "valid time"):
            validate_config_dict(data)

    def test_requires_at_least_one_anker_system(self) -> None:
        data = valid_config()
        data["sources"]["anker_systems"] = []

        with self.assertRaisesRegex(ConfigError, "anker_systems"):
            validate_config_dict(data)


if __name__ == "__main__":
    unittest.main()
