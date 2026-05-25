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
            elif self.path == "/icon.png":
                self._send_file(Path(__file__).resolve().parents[2] / "icon.png", content_type="image/png")
            elif self.path == "/logo.png":
                self._send_file(Path(__file__).resolve().parents[2] / "logo.png", content_type="image/png")
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

    def _send_file(self, path: Path, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = path.read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
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
  <link rel="icon" href="icon.png">
  <link rel="stylesheet" href="app.css">
</head>
<body>
  <svg class="symbols" aria-hidden="true">
    <symbol id="icon-refresh" viewBox="0 0 24 24"><path d="M21 12a9 9 0 0 1-15.4 6.4M3 12A9 9 0 0 1 18.4 5.6"/><path d="M21 4v6h-6M3 20v-6h6"/></symbol>
    <symbol id="icon-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></symbol>
    <symbol id="icon-grid" viewBox="0 0 24 24"><path d="M4 20h16M6 20V8l6-4 6 4v12M9 20v-7h6v7"/></symbol>
    <symbol id="icon-battery" viewBox="0 0 24 24"><path d="M4 7h14a2 2 0 0 1 2 2v1h1v4h-1v1a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z"/><path d="M6 10v4M9 10v4M12 10v4"/></symbol>
    <symbol id="icon-bolt" viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 10-13h-7l0-7Z"/></symbol>
    <symbol id="icon-pump" viewBox="0 0 24 24"><path d="M4 14h7a5 5 0 0 0 5-5V5h3v4a8 8 0 0 1-8 8H4Z"/><path d="M4 10h5M4 18h5M17 5h4"/></symbol>
    <symbol id="icon-check" viewBox="0 0 24 24"><path d="m4 12 5 5L20 6"/></symbol>
    <symbol id="icon-pause" viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></symbol>
    <symbol id="icon-alert" viewBox="0 0 24 24"><path d="M12 3 2 21h20Z"/><path d="M12 9v5M12 18h.01"/></symbol>
    <symbol id="icon-settings" viewBox="0 0 24 24"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z"/><path d="M4 12H2M22 12h-2M12 4V2M12 22v-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M18.4 5.6l1.4-1.4M4.2 19.8l1.4-1.4"/></symbol>
  </svg>
  <header>
    <div class="brand">
      <img src="icon.png" alt="">
      <div>
        <h1>Energy Surplus Bot</h1>
        <p id="lastRun">Lade Status...</p>
      </div>
    </div>
    <button id="refresh" type="button" title="Aktualisieren"><svg><use href="#icon-refresh"></use></svg><span>Aktualisieren</span></button>
  </header>
  <main>
    <section class="status-section">
      <h2>Status</h2>
      <div id="metricGrid" class="metric-grid"></div>
      <div class="split">
        <div>
          <h3>Entscheidungen</h3>
          <div id="decisions" class="list-panel"></div>
        </div>
        <div>
          <h3>Schaltstatus</h3>
          <div id="serviceCalls" class="list-panel"></div>
        </div>
      </div>
      <div id="warnings" class="warnings"></div>
    </section>
    <section class="config-section">
      <h2><svg><use href="#icon-settings"></use></svg> Konfiguration</h2>
      <p class="warning">Echte Schaltbefehle passieren nur bei auto_mode=true und dry_run=false.</p>
      <textarea id="config" spellcheck="false"></textarea>
      <button id="save" type="button">Speichern</button>
      <p id="saveResult"></p>
    </section>
    <section class="entities-section">
      <h2>Entities</h2>
      <input id="entityFilter" type="search" placeholder="Filtern">
      <ul id="entities"></ul>
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
"""


APP_CSS = """
:root {
  --bg: #eef3f1;
  --panel: #ffffff;
  --text: #18202a;
  --muted: #5f6b76;
  --line: #d8dee6;
  --green: #1f6f5e;
  --mint: #89cfb9;
  --sun: #ffd559;
  --warn: #b76b00;
  --danger: #b53d3d;
}

body {
  margin: 0;
  font-family: Arial, sans-serif;
  color: #18202a;
  background: var(--bg);
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
}

.symbols {
  display: none;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand img {
  width: 48px;
  height: 48px;
}

.brand p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 14px;
}

h1, h2, h3 {
  margin: 0;
}

main {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(360px, 1.2fr) minmax(360px, .8fr);
  padding: 16px;
}

section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
}

.status-section {
  grid-column: 1 / -1;
}

.config-section, .entities-section {
  min-width: 0;
}

h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
}

h3 {
  color: var(--muted);
  font-size: 13px;
  margin: 18px 0 8px;
  text-transform: uppercase;
}

button, input, textarea {
  font: inherit;
}

button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #6c7a89;
  background: #26384d;
  color: #ffffff;
  border-radius: 6px;
  padding: 8px 12px;
}

svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2;
  flex: 0 0 auto;
}

.metric-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  margin-top: 14px;
}

.metric-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: #fbfcfd;
}

.metric-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--muted);
  font-size: 13px;
}

.metric-card strong {
  display: block;
  font-size: 28px;
  margin-top: 10px;
}

.metric-card small {
  color: var(--muted);
}

.metric-card.good svg,
.decision.turn_on svg,
.decision.keep_on svg {
  color: var(--green);
}

.metric-card.warn svg,
.warning-icon {
  color: var(--warn);
}

.metric-card.sun svg {
  color: var(--sun);
}

.split {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
}

.list-panel {
  display: grid;
  gap: 8px;
}

.decision,
.service-call,
.entity-row {
  display: grid;
  grid-template-columns: 28px 1fr auto;
  gap: 10px;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background: #fbfcfd;
}

.decision strong,
.service-call strong {
  display: block;
}

.decision small,
.service-call small,
.entity-row small {
  color: var(--muted);
}

.badge {
  border-radius: 999px;
  padding: 4px 8px;
  background: #edf3f1;
  color: var(--green);
  font-size: 12px;
}

.badge.warn {
  background: #fff3d6;
  color: var(--warn);
}

.badge.danger {
  background: #ffe6e6;
  color: var(--danger);
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
  margin: 0;
  padding: 0;
  list-style: none;
}

li {
  margin: 8px 0;
}

@media (max-width: 860px) {
  header {
    align-items: flex-start;
    gap: 12px;
    flex-direction: column;
  }

  main {
    grid-template-columns: 1fr;
  }
}
"""


APP_JS = """
const lastRunEl = document.querySelector('#lastRun');
const metricGridEl = document.querySelector('#metricGrid');
const decisionsEl = document.querySelector('#decisions');
const serviceCallsEl = document.querySelector('#serviceCalls');
const warningsEl = document.querySelector('#warnings');
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
    getJson('api/config'),
    getJson('api/status'),
    getJson('api/entities'),
  ]);
  configEl.value = JSON.stringify(config, null, 2);
  renderStatus(status);
  entities = entityData;
  renderEntities();
}

function icon(name) {
  return `<svg><use href="#icon-${name}"></use></svg>`;
}

function formatW(value) {
  return `${Math.round(value || 0)} W`;
}

function formatPercent(value) {
  if (value === null || value === undefined) return 'unbekannt';
  return `${Number(value).toFixed(1)}%`;
}

function renderStatus(status) {
  const snapshot = status.snapshot;
  const ranAt = new Date(status.ran_at);
  lastRunEl.textContent = `Letzte Aktualisierung: ${ranAt.toLocaleString('de-DE')}`;
  metricGridEl.innerHTML = [
    metric('grid', 'Netzbezug', formatW(snapshot.grid_import_w), 'aktuell', snapshot.grid_import_w > 0 ? 'warn' : 'good'),
    metric('bolt', 'Einspeisung', formatW(snapshot.grid_export_w), 'aktuell', snapshot.grid_export_w > 0 ? 'good' : ''),
    metric('sun', 'PV Eingang', formatW(snapshot.solar_input_w), 'Anker gesamt', 'sun'),
    metric('bolt', 'Solar Ausgang', formatW(snapshot.solar_output_w), 'Anker gesamt', 'good'),
    metric('battery', 'Akku', formatPercent(snapshot.battery_soc_percent), snapshot.battery_near_target ? 'nahe Zielwert' : 'unter Zielwert', snapshot.battery_near_target ? 'good' : ''),
    metric('alert', 'Abregelrisiko', formatW(snapshot.solar_surplus_risk_w), 'durch Ausgangslimit', snapshot.solar_surplus_risk_w > 0 ? 'warn' : 'good'),
  ].join('');

  decisionsEl.innerHTML = status.decisions.length
    ? status.decisions.map(renderDecision).join('')
    : emptyPanel('pause', 'Keine Entscheidungen');

  serviceCallsEl.innerHTML = status.service_calls.length
    ? status.service_calls.map(renderServiceCall).join('')
    : emptyPanel('pause', 'Keine Schaltaktionen');

  warningsEl.innerHTML = snapshot.warnings && snapshot.warnings.length
    ? `<h3>Warnungen</h3>${snapshot.warnings.map(warning => `<div class="service-call">${icon('alert')}<div><strong>${escapeHtml(warning)}</strong><small>Sensorwert pruefen</small></div><span class="badge warn">Warnung</span></div>`).join('')}`
    : '';
}

function metric(iconName, label, value, subline, tone) {
  return `<article class="metric-card ${tone || ''}">
    <div class="metric-head"><span>${label}</span>${icon(iconName)}</div>
    <strong>${value}</strong>
    <small>${subline}</small>
  </article>`;
}

function renderDecision(decision) {
  const actionIcon = decision.action.includes('on') ? 'check' : decision.action.includes('off') ? 'pause' : 'bolt';
  const tone = decision.action === 'turn_off' ? 'danger' : decision.action === 'keep_off' ? 'warn' : '';
  return `<div class="decision ${decision.action}">
    ${icon(actionIcon)}
    <div>
      <strong>${escapeHtml(decision.device_name)}</strong>
      <small>${escapeHtml(decision.reason)} · Deckung ${Math.round(decision.solar_coverage_percent)}% · Laufzeit ${decision.runtime_today_minutes} min</small>
    </div>
    <span class="badge ${tone}">${decision.action}</span>
  </div>`;
}

function renderServiceCall(call) {
  const badge = call.skipped ? '<span class="badge warn">uebersprungen</span>' : '<span class="badge">bereit</span>';
  return `<div class="service-call">
    ${icon(call.skipped ? 'pause' : 'check')}
    <div>
      <strong>${escapeHtml(call.device_name)}</strong>
      <small>${escapeHtml(call.reason)}</small>
    </div>
    ${badge}
  </div>`;
}

function emptyPanel(iconName, text) {
  return `<div class="service-call">${icon(iconName)}<div><strong>${text}</strong><small>Aktuell kein Eintrag</small></div><span></span></div>`;
}

function renderEntities() {
  const filter = filterEl.value.toLowerCase();
  entitiesEl.innerHTML = '';
  for (const entity of entities) {
    const text = `${entity.entity_id} ${entity.friendly_name || ''} ${entity.state}`;
    if (filter && !text.toLowerCase().includes(filter)) continue;
    const item = document.createElement('li');
    item.className = 'entity-row';
    item.innerHTML = `${icon(entity.entity_id.startsWith('switch.') ? 'pump' : 'bolt')}
      <div><strong>${escapeHtml(entity.entity_id)}</strong><small>${escapeHtml(entity.friendly_name || '')}</small></div>
      <span class="badge">${escapeHtml(entity.state)}${entity.unit ? ' ' + escapeHtml(entity.unit) : ''}</span>`;
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
  const response = await fetch('api/config', {
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
  lastRunEl.textContent = error.message;
}));
document.querySelector('#save').addEventListener('click', () => saveConfig().catch(error => {
  saveResultEl.textContent = error.message;
}));
filterEl.addEventListener('input', renderEntities);
refresh().catch(error => {
  lastRunEl.textContent = error.message;
});

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}
"""
