# Implementierungsplan: Home Assistant Energy Surplus Bot

## Ziel des Plans

Dieser Plan beschreibt die Umsetzung vom leeren Repository zu einem lauffaehigen Home-Assistant-Add-on mit GUI, Dry-Run-Modus und erster automatischer Steuerung der Poolpumpe. Die Umsetzung erfolgt in kleinen, testbaren Phasen.

Aktueller Stand: Die Phasen 1 bis 9 sind als MVP umgesetzt. Es gibt Konfigurationsvalidierung, Home-Assistant-/Demo-Client, eingebaute Weboberflaeche, Messwertdiagnose, Runtime-Tracking, Dry-Run-Entscheidungen, Scheduler, Sicherheitsfreigabe ueber `auto_mode` und `dry_run` sowie Add-on-Paketdateien.

Leitprinzip:

- Erst beobachten und erklaeren.
- Dann im Dry-Run Entscheidungen pruefen.
- Erst danach echte Schaltbefehle erlauben.

## Technische Basis

Vorgeschlagener Stack:

- Python fuer Backend, Entscheidungslogik und Home-Assistant-Kommunikation
- FastAPI oder Flask fuer die Add-on-Weboberflaeche
- YAML/JSON als persistiertes Konfigurationsformat
- Docker-basiertes Home-Assistant-Add-on
- pytest fuer Entscheidungslogik und Konfigurationsvalidierung

Die GUI soll von Anfang an Teil des MVP sein. YAML-Dateien dienen nur als internes Format und als Debug-/Backup-Hilfe.

## Zielstruktur

```text
HomeAssistantEnergyBot/
  config.example.yaml
  config.yaml
  Dockerfile
  run.sh
  requirements.txt
  app/
    __init__.py
    main.py
    ha_client.py
    config_store.py
    models.py
    decision_engine.py
    scheduler.py
    runtime_tracker.py
    entity_registry.py
    diagnostics.py
    ui/
      __init__.py
      server.py
      static/
        app.css
        app.js
      templates/
        index.html
  tests/
    test_config_store.py
    test_decision_engine.py
    test_runtime_tracker.py
  docs/
    konzept.md
    implementierungsplan.md
```

## Phase 1: Projektgrundgeruest

Ziel: Das Add-on startet lokal als Python-App und kann seine Konfiguration laden.

Aufgaben:

- Python-Paketstruktur anlegen.
- `requirements.txt` anlegen.
- `config.example.yaml` als Vorlage verwenden.
- Konfigurationsmodelle fuer App, Home Assistant, Quellen, Akku und Verbraucher erstellen.
- Konfigurationsvalidierung einbauen.
- Minimalen Startpunkt `app/main.py` erstellen.
- Erste Tests fuer gueltige und ungueltige Konfigurationen schreiben.

Abnahmekriterien:

- `python -m app.main` startet ohne Home-Assistant-Verbindung im Dry-Run-/Demo-Modus.
- Fehlende Pflichtfelder werden verstaendlich gemeldet.
- Tests fuer Konfigurationsvalidierung laufen lokal.

## Phase 2: Home-Assistant-Client

Ziel: Das Add-on kann Home-Assistant-Entities lesen und Schaltbefehle technisch vorbereiten.

Aufgaben:

- REST-Client fuer Home Assistant implementieren.
- Entity-State lesen: `/api/states/<entity_id>`.
- Alle States lesen fuer Entity-Picker in der GUI.
- Service Call vorbereiten: `switch.turn_on` und `switch.turn_off`.
- Dry-Run-Schutz zentral einbauen, damit im Testbetrieb keine echten Service Calls passieren.
- Fehlerbehandlung fuer fehlende, unbekannte oder nicht numerische Sensorwerte.

Abnahmekriterien:

- Der Client kann konfigurierte Sensorwerte in Watt/Prozent als Zahlen bereitstellen.
- Dry-Run loggt geplante Schaltbefehle, fuehrt sie aber nicht aus.
- Bei ungueltigen Sensorwerten wird defensiv keine neue Last eingeschaltet.

## Phase 3: Konfigurations-GUI

Ziel: Die komplette Konfiguration ist ueber eine einfache Add-on-Weboberflaeche pflegbar.

Aufgaben:

- Webserver fuer GUI starten.
- Startseite mit Status, Auto-Modus, Dry-Run und letzter Entscheidung.
- Entity-Picker fuer:
  - Netzbezug
  - Einspeisung
  - Anker PV-Eingangsleistung
  - Anker Ausgangsleistung
  - Anker Akkustand
  - Anker Akkuleistung
  - schaltbare Verbraucher
- Formular fuer Akku-Strategie:
  - Ziel-SOC
  - Mindest-SOC
  - Nahe-Ziel-Marge
  - SOC-Aggregation
- Formular fuer Verbraucherprofile:
  - Name
  - Entity-ID
  - Leistung in Watt
  - Prioritaet
  - Mindestlaufzeit
  - Mindestpause
  - Tagesmindestlaufzeit
  - Tagesmaximallaufzeit
  - Zeitfenster
  - Mindestdeckung durch Solar/Ueberschuss
  - Pflichtlaufzeit erlauben
- Speichern in persistentes Configformat.
- Laden der gespeicherten Konfiguration beim Start.

Abnahmekriterien:

- Ein Nutzer kann die Beispielkonfiguration vollstaendig ueber die GUI nachbauen.
- Ohne direkte YAML-Bearbeitung koennen zwei Anker-Systeme und mindestens zwei Verbraucher konfiguriert werden.
- Nach Neustart bleibt die Konfiguration erhalten.

## Phase 4: Messwert-Aggregation und Diagnose

Ziel: Aus den ausgewaehlten Entities entsteht ein konsistenter Energiezustand.

Aufgaben:

- PV-Eingangsleistung ueber beide Anker-Geraete summieren.
- Solar-Ausgangsleistung summieren.
- Batterieleistung summieren.
- Akkustand pro Geraet lesen und nach Strategie aggregieren, initial `min`.
- Netzbezug und Einspeisung getrennt lesen.
- Ueberschuss berechnen.
- Solar-Abregelrisiko wegen 800-W-Ausgangsbegrenzung berechnen.
- Diagnoseobjekt fuer GUI und Log erstellen.

Abnahmekriterien:

- GUI zeigt aktuelle aggregierte Werte.
- Diagnose erklaert, ob gerade Ueberschuss, Netzbezug oder Abregelrisiko besteht.
- Fehlende Einzelwerte werden sichtbar gemeldet.

## Phase 5: Runtime-Tracking

Ziel: Das Add-on kennt Laufzeiten und Schaltsperren pro Verbraucher.

Aufgaben:

- Laufzeit pro Verbraucher fuer den aktuellen Tag erfassen.
- Letzten Einschalt- und Ausschaltzeitpunkt speichern.
- Mindestlaufzeit pruefen.
- Mindestpause pruefen.
- Tagesmindestlaufzeit und Tagesmaximallaufzeit pruefen.
- Tageswechsel korrekt behandeln.
- Persistenz fuer Runtime-State einbauen.

Abnahmekriterien:

- Poolpumpe bekommt korrekte `runtime_today_minutes`.
- Nach Neustart gehen Tageslaufzeiten nicht verloren.
- Tageswechsel setzt Tageswerte kontrolliert zurueck.

## Phase 6: Entscheidungslogik im Dry-Run

Ziel: Die App trifft nachvollziehbare Entscheidungen, schaltet aber noch nicht real.

Aufgaben:

- Entscheidungsmodell erstellen: `turn_on`, `turn_off`, `keep_on`, `keep_off`, `no_action`.
- Begruendung je Entscheidung erzeugen.
- Poolpumpen-Regeln implementieren:
  - Zeitfenster beachten
  - Mindestlaufzeit 8 Stunden pro Tag
  - Mindestdeckung 70 Prozent
  - Netzbezug erlauben, wenn Tagesziel sonst nicht erreichbar ist
  - Mindestlaufzeit und Mindestpause beachten
- Akku-Regeln implementieren:
  - Ziel-SOC initial 80 Prozent
  - nahe Zielwert frueher Lasten starten
  - unter Mindest-SOC defensiv bleiben
- Solarbox-Regel implementieren:
  - bei hoher PV-Eingangsleistung, begrenztem Ausgang und Akku nahe Zielwert flexible Verbraucher frueher starten
- Prioritaet zwischen Verbrauchern vorbereiten.

Abnahmekriterien:

- Dry-Run zeigt fuer jede Entscheidung eine klare Begruendung.
- Tests decken mindestens diese Szenarien ab:
  - viel Einspeisung, Poolpumpe aus
  - Netzbezug, Poolpumpe Mindestlaufzeit noch nicht erreicht
  - Poolpumpe muss laufen, weil Tagesfenster knapp wird
  - Akku unter Mindest-SOC
  - Akku nahe 80 Prozent und hohes Abregelrisiko
  - Entfeuchter laeuft nur bei Ueberschuss

## Phase 7: Scheduler und Betriebsmodus

Ziel: Das Add-on laeuft dauerhaft und entscheidet in festen Intervallen.

Aufgaben:

- Scheduler mit konfigurierbarem Intervall implementieren.
- Werte ueber 3 bis 5 Minuten glaetten.
- Auto-Modus global beachten.
- Dry-Run global beachten.
- Letzte Entscheidung fuer GUI speichern.
- Logausgabe strukturieren.
- Fehler so behandeln, dass der Scheduler weiterlaeuft.

Abnahmekriterien:

- Die App laeuft dauerhaft ohne manuelle Eingriffe.
- GUI zeigt letzte Entscheidung und aktuellen Betriebszustand.
- Bei Home-Assistant-Fehlern bleibt das System defensiv.

## Phase 8: Echtes Schalten mit Sicherheitsfreigabe

Ziel: Nach erfolgreichem Dry-Run koennen echte Schaltbefehle aktiviert werden.

Aufgaben:

- Dry-Run in GUI sichtbar und bewusst deaktivierbar machen.
- Warnhinweis vor echtem Schalten anzeigen.
- Service Calls fuer Verbraucher ausfuehren.
- Manuelle Schaltungen erkennen und Strategie festlegen.
- Optional: Verbraucher temporar sperren.
- Schalthistorie anzeigen.

Abnahmekriterien:

- Echte Service Calls passieren nur bei `auto_mode: true` und `dry_run: false`.
- Jede Schaltaktion wird mit Zeit, Geraet und Begruendung geloggt.
- Manuelle Eingriffe fuehren nicht zu hektischem Zurueckschalten.

## Phase 9: Home-Assistant-Add-on-Paket

Ziel: Das Projekt ist als Add-on installierbar.

Aufgaben:

- `Dockerfile` erstellen.
- `run.sh` erstellen.
- Add-on-Konfigurationsdatei erstellen.
- Port fuer GUI freigeben.
- Persistenten `/data`-Speicher verwenden.
- README mit Installation und Erstkonfiguration schreiben.
- Beispielwerte dokumentieren.

Abnahmekriterien:

- Add-on laesst sich in Home Assistant starten.
- GUI ist erreichbar.
- Konfiguration ueberlebt Add-on-Neustart.
- Logs sind im Add-on-Log sichtbar.

## Phase 10: Erweiterungen nach MVP

Nach dem ersten lauffaehigen Add-on:

- Entfeuchter als aktiv getesteter zweiter Verbraucher.
- Statussensoren zurueck nach Home Assistant schreiben.
- Tagesauswertung fuer Eigenverbrauch und vermiedene Einspeisung.
- Wetter- und Solarprognose.
- Lernende Laufzeitplanung aus historischen Daten.
- Bessere Priorisierung mehrerer Verbraucher.
- Import/Export der Konfiguration.

## Reihenfolge der naechsten konkreten Arbeiten

1. Projektgrundgeruest und Python-Modelle anlegen.
2. Konfigurationsvalidierung fuer `config.example.yaml` implementieren.
3. Minimalen GUI-Server starten.
4. Entity-Picker vorbereiten, zunaechst mit Mockdaten.
5. Home-Assistant-Client anschliessen.
6. Aggregation und Dry-Run-Entscheidungen implementieren.

## Risiken

- Home-Assistant-Entity-Namen und Einheiten koennen je Integration unterschiedlich sein.
- Anker-Sensoren koennen Werte zeitverzoegert oder kurzzeitig `unknown` liefern.
- Tageslaufzeit muss auch bei Neustarts korrekt bleiben.
- Zu aggressive Regeln koennen ungewollten Netzbezug erzeugen.
- Zu defensive Regeln koennen Eigenverbrauchspotenzial verschenken.

## Sicherheitsentscheidungen fuer den MVP

- Default ist `dry_run: true`.
- Default ist `auto_mode: false`.
- Fehlende oder unplausible Sensorwerte verhindern neue Einschaltungen.
- Ausschaltungen beachten Mindestlaufzeit.
- Einschaltungen beachten Mindestpause.
- Echte Schaltbefehle brauchen explizite Freigabe in der GUI.
