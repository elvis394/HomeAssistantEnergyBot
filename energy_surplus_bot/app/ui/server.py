from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from app.config_store import load_config, validate_config_dict
from app.ha_client import DemoHomeAssistantClient, HomeAssistantClient, HomeAssistantError
from app.models import ConfigError, EnergyBotConfig
from app.runtime_tracker import RuntimeState, load_runtime_state, save_runtime_state
from app.scheduler import EnergyBotClient, run_once


ClientFactory = Callable[[EnergyBotConfig], EnergyBotClient]


def default_client_factory(use_live_ha: bool) -> ClientFactory:
    def build(config: EnergyBotConfig) -> EnergyBotClient:
        if use_live_ha:
            return HomeAssistantClient.from_config(config)
        return DemoHomeAssistantClient.from_config(config)

    return build


def config_to_dict(config: EnergyBotConfig) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(config)))


def build_status_payload(
    config: EnergyBotConfig,
    client: EnergyBotClient,
    runtime_state: RuntimeState,
    now: datetime | None = None,
) -> dict[str, Any]:
    result = run_once(config, client, runtime_state, now=now)
    return {
        "ran_at": result.ran_at.isoformat(),
        "snapshot": asdict(result.snapshot),
        "decisions": [asdict(decision) for decision in result.decisions],
        "service_calls": [asdict(call) for call in result.service_calls],
        "device_states": result.device_states,
    }


def list_entity_payload(client: EnergyBotClient) -> list[dict[str, Any]]:
    if not hasattr(client, "list_states"):
        return []
    states = client.list_states()  # type: ignore[attr-defined]
    return [
        {
            "entity_id": state.entity_id,
            "state": state.state,
            "friendly_name": state.attributes.get("friendly_name", state.entity_id),
            "unit": state.attributes.get("unit_of_measurement"),
        }
        for state in states
    ]


class EnergyBotRequestHandler(BaseHTTPRequestHandler):
    server: EnergyBotHttpServer

    def do_GET(self) -> None:
        try:
            if self.path == "/":
                self._send_text(INDEX_HTML, content_type="text/html")
            elif self.path == "/app.css":
                self._send_text(APP_CSS, content_type="text/css")
            elif self.path == "/app.js":
                self._send_text(APP_JS, content_type="application/javascript")
            elif self.path == "/api/config":
                self._send_json(config_to_dict(self.server.load_config()))
            elif self.path == "/api/entities":
                config = self.server.load_config()
                client = self.server.client_factory(config)
                self._send_json(list_entity_payload(client))
            elif self.path == "/api/status":
                config = self.server.load_config()
                client = self.server.client_factory(config)
                runtime_state = load_runtime_state(self.server.runtime_path)
                payload = build_status_payload(config, client, runtime_state)
                save_runtime_state(self.server.runtime_path, runtime_state)
                self._send_json(payload)
            else:
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except (ConfigError, HomeAssistantError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        try:
            if self.path != "/api/config":
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw)
            config = validate_config_dict(data)
            self.server.save_config(config)
            self._send_json({"ok": True, "config": config_to_dict(config)})
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"invalid JSON: {exc}"}, status=HTTPStatus.BAD_REQUEST)
        except ConfigError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"ui: {self.address_string()} - {format % args}")

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, payload: str, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class EnergyBotHttpServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        config_path: str | Path,
        runtime_path: str | Path,
        client_factory: ClientFactory,
    ) -> None:
        super().__init__(server_address, EnergyBotRequestHandler)
        self.config_path = Path(config_path)
        self.runtime_path = Path(runtime_path)
        self.client_factory = client_factory
        self.latest_status: dict[str, Any] | None = None
        self.latest_error: str | None = None
        self._scheduler_started = False

    def load_config(self) -> EnergyBotConfig:
        return load_config(self.config_path)

    def save_config(self, config: EnergyBotConfig) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            json.dump(config_to_dict(config), handle, indent=2)

    def start_scheduler(self) -> None:
        if self._scheduler_started:
            return
        self._scheduler_started = True
        thread = threading.Thread(target=self._scheduler_loop, name="energy-bot-scheduler", daemon=True)
        thread.start()

    def _scheduler_loop(self) -> None:
        while True:
            interval = 30
            try:
                config = self.load_config()
                interval = config.app.decision_interval_seconds
                client = self.client_factory(config)
                runtime_state = load_runtime_state(self.runtime_path)
                self.latest_status = build_status_payload(config, client, runtime_state)
                self.latest_error = None
                save_runtime_state(self.runtime_path, runtime_state)
            except Exception as exc:  # Keep the add-on alive and visible after transient HA errors.
                self.latest_error = str(exc)
            time.sleep(max(5, interval))


def serve_ui(
    config_path: str | Path,
    runtime_path: str | Path,
    host: str,
    port: int,
    use_live_ha: bool = False,
    run_scheduler: bool = True,
) -> None:
    server = EnergyBotHttpServer(
        (host, port),
        config_path=config_path,
        runtime_path=runtime_path,
        client_factory=default_client_factory(use_live_ha),
    )
    if run_scheduler:
        server.start_scheduler()
    print(f"Energy Bot UI listening on http://{host}:{port}")
    server.serve_forever()


INDEX_HTML = """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Energy Surplus Bot</title>
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <header>
    <h1>Energy Surplus Bot</h1>
    <button id="refresh" type="button">Aktualisieren</button>
  </header>
  <main>
    <section>
      <h2>Status</h2>
      <pre id="status">Lade...</pre>
    </section>
    <section>
      <h2>Konfiguration</h2>
      <p class="warning">Echte Schaltbefehle passieren nur bei auto_mode=true und dry_run=false.</p>
      <textarea id="config" spellcheck="false"></textarea>
      <button id="save" type="button">Speichern</button>
      <p id="saveResult"></p>
    </section>
    <section>
      <h2>Entities</h2>
      <input id="entityFilter" type="search" placeholder="Filtern">
      <ul id="entities"></ul>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""


APP_CSS = """
body {
  margin: 0;
  font-family: Arial, sans-serif;
  color: #18202a;
  background: #f5f7f9;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  background: #ffffff;
  border-bottom: 1px solid #d8dee6;
}

h1, h2 {
  margin: 0;
}

main {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  padding: 16px;
}

section {
  background: #ffffff;
  border: 1px solid #d8dee6;
  border-radius: 8px;
  padding: 16px;
}

button, input, textarea {
  font: inherit;
}

button {
  border: 1px solid #6c7a89;
  background: #26384d;
  color: #ffffff;
  border-radius: 6px;
  padding: 8px 12px;
}

textarea {
  box-sizing: border-box;
  width: 100%;
  min-height: 520px;
  margin: 12px 0;
  font-family: Consolas, monospace;
  font-size: 13px;
}

pre {
  overflow: auto;
  white-space: pre-wrap;
}

.warning {
  color: #8a4b00;
  background: #fff3d6;
  border: 1px solid #e6c26a;
  border-radius: 6px;
  padding: 8px;
}

input {
  box-sizing: border-box;
  width: 100%;
  margin: 12px 0;
  padding: 8px;
}

ul {
  list-style: none;
  margin: 0;
  padding: 0;
}

li {
  border-top: 1px solid #edf0f3;
  padding: 8px 0;
}
"""


APP_JS = """
const statusEl = document.querySelector('#status');
const configEl = document.querySelector('#config');
const saveResultEl = document.querySelector('#saveResult');
const entitiesEl = document.querySelector('#entities');
const filterEl = document.querySelector('#entityFilter');
let entities = [];

async function getJson(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

async function refresh() {
  const [config, status, entityData] = await Promise.all([
    getJson('/api/config'),
    getJson('/api/status'),
    getJson('/api/entities'),
  ]);
  configEl.value = JSON.stringify(config, null, 2);
  statusEl.textContent = JSON.stringify(status, null, 2);
  entities = entityData;
  renderEntities();
}

function renderEntities() {
  const filter = filterEl.value.toLowerCase();
  entitiesEl.innerHTML = '';
  for (const entity of entities) {
    const text = `${entity.entity_id} ${entity.friendly_name || ''} ${entity.state}`;
    if (filter && !text.toLowerCase().includes(filter)) continue;
    const item = document.createElement('li');
    item.textContent = `${entity.entity_id} = ${entity.state}${entity.unit ? ' ' + entity.unit : ''}`;
    entitiesEl.appendChild(item);
  }
}

async function saveConfig() {
  saveResultEl.textContent = '';
  let payload;
  try {
    payload = JSON.parse(configEl.value);
  } catch (error) {
    saveResultEl.textContent = `JSON-Fehler: ${error.message}`;
    return;
  }
  const response = await fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    saveResultEl.textContent = data.error || 'Speichern fehlgeschlagen';
    return;
  }
  saveResultEl.textContent = 'Gespeichert';
  configEl.value = JSON.stringify(data.config, null, 2);
}

document.querySelector('#refresh').addEventListener('click', () => refresh().catch(error => {
  statusEl.textContent = error.message;
}));
document.querySelector('#save').addEventListener('click', () => saveConfig().catch(error => {
  saveResultEl.textContent = error.message;
}));
filterEl.addEventListener('input', renderEntities);
refresh().catch(error => {
  statusEl.textContent = error.message;
});
"""
