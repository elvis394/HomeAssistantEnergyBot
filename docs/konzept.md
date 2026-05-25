# Konzept: Home Assistant Energy Surplus Bot

## Ziel

Das Add-on soll ueberschuessige Energie im Haus automatisch sinnvoll verbrauchen, ohne Komfort, Geraeteschutz oder manuelle Kontrolle zu gefaehrden. Es nutzt Energie- und Geraetedaten aus Home Assistant, insbesondere Werte von zwei Anker-Solix-Geraeten, und schaltet geeignete Verbraucher wie eine Poolpumpe, Entfeuchter, Heizstab oder Ladegeraete automatisch an und aus.

Der erste Fokus liegt auf einer Poolpumpe als steuerbarem Verbraucher. Das System soll spaeter mehrere Verbraucher priorisieren und so steuern, dass die Eigenverbrauchsquote moeglichst hoch wird.

## Grundidee

Das Add-on beobachtet laufend:

- aktuelle Solarleistung
- Einspeisung und Netzbezug als getrennte Sensoren
- Akkuladestand
- Lade- oder Entladeleistung des Akkus
- Tageszeit und Wetter-/Solarfenster, sofern verfuegbar
- typische Leistung und Mindestlaufzeiten einzelner Verbraucher
- manuelle Sperren oder Prioritaeten

Daraus berechnet es, ob gerade genug Energieueberschuss vorhanden ist, um ein Geraet einzuschalten, ob ein aktives Geraet wieder abgeschaltet werden sollte, oder ob ein Geraet vorsorglich gestartet werden sollte, weil sonst Solarleistung nicht sinnvoll genutzt werden kann.

Ein wichtiger Sonderfall ist die Leistungsbegrenzung der Solarbox: Wenn die Solarbox maximal 800 W ausgeben kann, die Solarpanele aber deutlich mehr liefern koennen, soll das Add-on fruehzeitig zusaetzliche Verbraucher einschalten. So wird vermieden, dass Energie ungenutzt bleibt oder der Akku ueber das gewuenschte Ziel hinaus geladen wird.

## Wichtige Datenquellen

### Home Assistant Sensoren

Das Add-on sollte nicht direkt an einzelne Hersteller-APIs gekoppelt sein, sondern primaer Home-Assistant-Entities lesen. Dadurch bleibt es flexibel, auch wenn Anker Solix oder andere Integrationen spaeter geaendert werden.

Typische Sensoren:

- `sensor.solar_input_power`: PV-Eingangsleistung der Anker-Geraete
- `sensor.solar_output_power`: Ausgangsleistung der Anker-Geraete
- `sensor.grid_import_power`: aktueller Netzbezug ohne Vorzeichen
- `sensor.grid_export_power`: aktuelle Einspeisung ohne Vorzeichen
- `sensor.battery_soc`: Akkuladestand in Prozent
- `sensor.battery_power`: Lade- oder Entladeleistung des Akkus
- `sensor.house_power`: aktueller Hausverbrauch
- `sensor.energy_today`: Tagesertrag

Da zwei Anker-Solix-Geraete vorhanden sind, muss das Add-on mehrere Quellen desselben Typs unterstuetzen und ihre Werte sinnvoll aggregieren koennen. Pro Geraet gibt es einen System-Akkustand. PV-Eingangsleistung und Ausgangsleistung sind getrennt verfuegbar.

Beispiel fuer mehrere Quellen:

```yaml
sources:
  solar_input_power_entities:
    - sensor.anker_1_solar_input_power
    - sensor.anker_2_solar_input_power
  solar_output_power_entities:
    - sensor.anker_1_solar_output_power
    - sensor.anker_2_solar_output_power
  battery_soc_entities:
    - sensor.anker_1_battery_soc
    - sensor.anker_2_battery_soc
  battery_power_entities:
    - sensor.anker_1_battery_power
    - sensor.anker_2_battery_power
  grid_import_power_entity: sensor.grid_import_power
  grid_export_power_entity: sensor.grid_export_power
```

Aggregation:

- PV-Eingangsleistung wird summiert.
- Ausgangsleistung wird summiert.
- Batterieleistung wird summiert.
- Akkuladestand kann als niedrigster Wert, Durchschnitt oder gewichteter Durchschnitt betrachtet werden. Fuer den MVP ist der niedrigste SOC defensiv und einfach nachvollziehbar.
- Netzbezug und Einspeisung kommen aus zwei getrennten Sensoren ohne Vorzeichen. Einspeisung ist die wichtigste Wahrheit fuer aktuell verfuegbaren Ueberschuss, Netzbezug die wichtigste Wahrheit fuer unerwuenschten Zukauf.

### Konfigurations-GUI

Die gesamte Konfiguration soll ueber eine GUI moeglich sein. YAML ist nur das interne Speicher- und Debugformat, nicht der erwartete Bedienweg.

- Auswahl der PV-Eingangsleistungs-Entities
- Auswahl der Solar-Ausgangsleistungs-Entities
- Auswahl der Akku-SOC-Entities
- Auswahl der Akku-Leistungs-Entities
- Auswahl des Netzbezugssensors
- Auswahl des Einspeisesensors
- Auswahl schaltbarer Verbraucher
- Einstellung von Leistung, Mindestlaufzeit, Mindestpause, Tageslaufzeit, Prioritaet, erlaubtem Netzanteil und Zeitfenstern pro Verbraucher
- Einstellung des Akku-Zielwerts
- Einstellung der Solarbox-Ausgangsbegrenzung
- Dry-Run-Schalter
- Auto-Modus-Schalter
- Anzeige der letzten Entscheidung mit Begruendung

Fuer den MVP soll eine einfache Add-on-Weboberflaeche reichen. Sie muss nicht schoen sein, aber vollstaendig genug, um ohne manuelles Bearbeiten von YAML betrieben zu werden.

### Schaltbare Verbraucher

Verbraucher werden als Home-Assistant-Entities modelliert:

- `switch.pool_pump`
- `switch.dehumidifier`
- `switch.heating_rod`
- `switch.ev_charger_enable`

Jeder Verbraucher bekommt ein Profil mit typischer Leistung, Mindestlaufzeit, Mindestpause, Prioritaet, Tageslaufzeit und optionalen Zeitfenstern.

## Verbraucherprofile

Beispiel Poolpumpe:

```yaml
devices:
  - name: pool_pump
    entity_id: switch.pool_pump
    power_w: 450
    priority: 10
    min_run_minutes: 30
    min_off_minutes: 20
    min_daily_runtime_minutes: 480
    max_daily_runtime_minutes: 720
    preferred_window:
      start: "09:00"
      end: "18:00"
    min_solar_coverage_percent: 70
    allow_grid_import_w: 135
    battery_min_soc: 55
    force_complete_daily_runtime: true
```

Bedeutung:

- Die Pumpe braucht ungefaehr 450 W.
- Sie darf bevorzugt tagsueber laufen.
- Sie soll nach dem Einschalten mindestens 30 Minuten laufen.
- Nach dem Ausschalten soll sie mindestens 20 Minuten aus bleiben.
- Sie soll mindestens 8 Stunden pro Tag laufen.
- Sie darf bis zu 12 Stunden laufen, wenn viel Ueberschuss vorhanden ist.
- Sie darf regulaer laufen, wenn mindestens 70 Prozent ihres Verbrauchs durch Solar-/Ueberschussenergie gedeckt sind.
- Kurzzeitiger Netzbezug bis 135 W ist bei 450 W Verbrauch toleriert, weil dann noch 70 Prozent gedeckt sind.
- Sie darf auch mit mehr Netzbezug laufen, wenn sie sonst ihre Mindestlaufzeit im Tagesfenster nicht mehr erreicht.

Beispiel Entfeuchter:

```yaml
devices:
  - name: dehumidifier
    entity_id: switch.dehumidifier
    power_w: 300
    priority: 20
    min_run_minutes: 20
    min_off_minutes: 20
    min_daily_runtime_minutes: 0
    max_daily_runtime_minutes: 180
    preferred_window:
      start: "10:00"
      end: "20:00"
    min_solar_coverage_percent: 80
    battery_min_soc: 65
```

Der Entfeuchter waere damit niedriger priorisiert als die Poolpumpe und laeuft eher als flexibler Zusatzverbraucher.

## Akku-Strategie

Der Akku soll nicht pauschal immer zuerst vollgeladen werden. Stattdessen soll es ein konfigurierbares Zielband geben.

Beispiel:

```yaml
battery:
  target_soc_percent: 80
  minimum_soc_percent: 30
  reserve_for_evening_percent: 50
  over_target_action: prefer_consumers
```

Grundregeln:

- Unterhalb einer Mindestgrenze werden flexible Verbraucher nur sehr vorsichtig gestartet.
- Bis zum Zielwert, z. B. 80 Prozent, darf der Akku bevorzugt geladen werden.
- Naehert sich der Akku dem Zielwert und ist weiterhin hohe Solarleistung verfuegbar, werden zusaetzliche Verbraucher frueher eingeschaltet.
- Oberhalb des Zielwerts werden flexible Verbraucher bevorzugt, damit der Akku nicht unnoetig weiter geladen wird.
- Der Zielwert muss konfigurierbar sein, weil Saison, Wetter und persoenlicher Verbrauch unterschiedlich sind.

Das Ziel ist nicht "Akku immer voll", sondern "moeglichst viel Solarenergie selbst verbrauchen, ohne den Akku unnoetig hoch zu halten".

## Steuerlogik

### Ueberschussberechnung

Eine robuste erste Formel:

```text
available_surplus_w =
  exported_power_w
  + optional_battery_charge_power_w
  - reserve_w
```

Falls kein sauberer Einspeisesensor vorhanden ist:

```text
available_surplus_w =
  solar_power_w
  - house_power_w
  - battery_charge_target_w
  - reserve_w
```

Da getrennte Sensoren fuer Netzbezug und Einspeisung vorhanden sind, sollte der MVP diese Sensoren als fuehrende Groessen nutzen. Solar- und Akkusensoren dienen zusaetzlich zur Einschaetzung, ob gerade echter Ueberschuss, Akkuentladung oder ein begrenzter Solarbox-Ausgang vorliegt.
Da Netzbezug und Einspeisung getrennte Sensoren ohne Vorzeichen sind, entfaellt im Normalfall die fehleranfaellige Vorzeichenkonfiguration.

Empfohlen ist ein konfigurierbarer Sicherheitsabstand, z. B. `reserve_w: 150`.

### Prognose gegen ungenutzte Solarleistung

Bei der Anker-Solix-Konstellation ist wichtig:

```text
panel_surplus_risk =
  solar_input_power_w
  - solarbox_output_limit_w
  - current_battery_charge_capacity_w
```

Wenn dieses Risiko steigt, der Akku nahe am Ziel-SOC ist und Verbraucher verfuegbar sind, sollte das Add-on Verbraucher frueher einschalten, auch wenn der reine Netzsensor noch keinen grossen Einspeiseueberschuss zeigt.

Fuer den MVP kann daraus eine einfache Regel werden:

- Akku-SOC groesser als `target_soc_percent - 5`
- Solarleistung stabil hoch
- kein oder nur geringer Netzbezug
- flexibler Verbraucher verfuegbar

Dann darf ein Verbraucher gestartet werden, wenn seine Mindestdeckung erreicht werden kann.

### Einschalten

Ein Geraet darf eingeschaltet werden, wenn:

- es aktuell aus ist
- genug Ueberschuss fuer seine typische Leistung vorhanden ist
- Akku-SOC ueber dem Mindestwert liegt oder nahe am Zielwert ist
- kein Mindest-Aus-Zeitraum verletzt wird
- das erlaubte Zeitfenster passt
- Tageslimit noch nicht erreicht ist
- keine manuelle Sperre aktiv ist
- die konfigurierte Mindestdeckung durch Solar-/Ueberschussenergie erreicht wird
- oder die Tagesmindestlaufzeit sonst nicht mehr erreichbar waere

### Ausschalten

Ein Geraet darf ausgeschaltet werden, wenn:

- es aktuell an ist
- Mindestlaufzeit erreicht ist
- laenger als eine definierte Toleranz Netzbezug entsteht
- Akku-SOC unter einen kritischen Wert faellt
- Zeitfenster endet
- Tageslimit erreicht ist
- der Solar-/Ueberschussanteil dauerhaft unter die erlaubte Mindestdeckung faellt und keine Pflichtlaufzeit mehr offen ist

Wichtig: Es sollte eine Hysterese geben. Einschalten und Ausschalten duerfen nicht bei denselben Grenzwerten passieren, sonst schaltet das System bei wechselnder Bewoelkung zu oft.

Beispiel:

- Einschalten bei mindestens `device_power_w + 150 W` Ueberschuss fuer 5 Minuten
- Ausschalten erst bei mehr als `200 W` Netzbezug fuer 10 Minuten

### Tageslaufzeit-Planung

Fuer Geraete mit Mindestlaufzeit, z. B. die Poolpumpe, reicht eine reine Momentanlogik nicht aus. Das Add-on muss pruefen, wie viel Laufzeit heute noch offen ist und wie viel nutzbares Tagesfenster verbleibt.

Beispiel:

```text
remaining_required_runtime =
  min_daily_runtime_minutes
  - runtime_today_minutes

remaining_window_minutes =
  minutes_until_preferred_window_end
```

Wenn `remaining_required_runtime` fast so gross ist wie `remaining_window_minutes`, muss die Pumpe laufen, auch wenn zeitweise Netzstrom benoetigt wird. Das passt zu der Regel: Netzstrom ist akzeptabel, wenn die Mindestlaufzeit sonst tagsueber nicht erreicht wird.

## Entscheidungsstrategie

Fuer den Anfang reicht ein regelbasierter Scheduler:

1. Sensordaten einlesen.
2. Werte glaetten, z. B. gleitender Durchschnitt ueber 3 bis 5 Minuten.
3. Akkuziel, Solarbox-Limit und Netzsensor bewerten.
4. Verfuegbaren Ueberschuss und Solar-Abregelrisiko berechnen.
5. Tageslaufzeit pro Verbraucher aktualisieren.
6. Laufende Geraete pruefen: muessen sie aus?
7. Pflichtlaufzeiten pruefen: muss ein Geraet laufen, um sein Tagesziel zu erreichen?
8. Ausgeschaltete Geraete nach Prioritaet pruefen: darf eines an?
9. Schaltaktion ausfuehren.
10. Entscheidung im Log und optional in Home Assistant sichtbar machen.

Spaeter kann daraus eine intelligentere Prognose entstehen, z. B. mit historischen Laufzeiten, Wetterdaten, Sonnenstand und typischen Lastprofilen. Der Begriff "KI" sollte hier praktisch verstanden werden: erst robuste Regeln, dann lernende Prognosen, sobald genug echte Daten vorliegen.

## Home-Assistant-Integration

Das Add-on sollte ueber die Home-Assistant-REST-API oder WebSocket-API arbeiten.

Es braucht:

- Long-Lived Access Token oder Add-on-Ingress/Auth, je nach Implementierung
- Zugriff auf Entity States
- Service Calls fuer `switch.turn_on` und `switch.turn_off`
- eigene Sensoren fuer Status und Diagnose

Eigene Entities waeren sinnvoll:

- `sensor.energy_bot_surplus_w`
- `sensor.energy_bot_grid_import_w`
- `sensor.energy_bot_grid_export_w`
- `sensor.energy_bot_solar_input_w`
- `sensor.energy_bot_solar_output_w`
- `sensor.energy_bot_solar_coverage_percent`
- `sensor.energy_bot_battery_target_soc`
- `sensor.energy_bot_runtime_pool_pump_today`
- `sensor.energy_bot_mode`
- `sensor.energy_bot_last_decision`
- `binary_sensor.energy_bot_pool_pump_allowed`
- `binary_sensor.energy_bot_solar_surplus_risk`
- `switch.energy_bot_auto_mode`

## Sicherheitsprinzipien

Das System soll defensiv schalten:

- Bei fehlenden oder unplausiblen Sensordaten keine neuen Verbraucher einschalten.
- Bestehende Verbraucher nur abschalten, wenn das Geraeteprofil das erlaubt.
- Manuelle Schaltungen des Nutzers respektieren.
- Optionaler Wartungsmodus pro Geraet.
- Mindestlaufzeiten und Mindestpausen strikt beachten.
- Maximal erlaubter Netzbezug konfigurierbar.
- Mindestdeckung durch Solarenergie pro Verbraucher beachten.
- Pflichtlaufzeiten transparent begruenden, wenn dafuer Netzstrom genutzt wird.
- Jede Schaltentscheidung nachvollziehbar loggen.

## Add-on-Aufbau

Moegliche Struktur:

```text
HomeAssistantEnergyBot/
  config.yaml
  Dockerfile
  run.sh
  app/
    main.py
    ha_client.py
    config.py
    scheduler.py
    models.py
    decision_engine.py
    runtime_tracker.py
    entity_registry.py
    ui/
      server.py
      static/
      templates/
  docs/
    konzept.md
```

Python ist fuer den Start gut geeignet, weil Home-Assistant-APIs, YAML-Konfiguration und Zeitlogik einfach abbildbar sind.

## MVP

Der erste sinnvolle MVP:

- Ein konfigurierbarer Verbraucher: Poolpumpe
- Lesen von PV-Eingangsleistung, Solar-Ausgangsleistung, Netzbezug, Einspeisung und Akkustand aus Home Assistant
- Unterstuetzung fuer zwei Anker-Solix-Quellen
- getrennte Unterstuetzung fuer Netzbezug und Einspeisung
- einfache GUI fuer die komplette Konfiguration
- Regelbasierte Start-/Stopp-Entscheidung
- Mindestlaufzeit, Mindestpause und Tagesmindestlaufzeit
- konfigurierbares Akku-Ziel, initial 80 Prozent
- Mindestdeckung durch Solar-/Ueberschussenergie, initial 70 Prozent fuer die Poolpumpe
- Pflichtlaufzeit-Logik, damit die Poolpumpe mindestens 8 Stunden tagsueber erreicht
- Auto-Modus global aktivierbar/deaktivierbar
- Dry-Run-Modus, der Entscheidungen nur loggt
- Diagnoseausgabe als Log

Noch nicht im MVP:

- Wetterprognose
- komplexe Optimierung ueber mehrere konkurrierende Verbraucher
- Optimierung ueber den ganzen Tag
- Lernen historischer Verbrauchsmuster

Direkt nach dem MVP:

- Entfeuchter als zweites Verbraucherprofil
- Statussensoren in Home Assistant
- Tagesauswertung: Eigenverbrauch, Netzbezug durch Automatik, vermiedene Einspeisung

## Geklaerte Anforderungen

- Es gibt zwei Anker-Solix-Geraete.
- Die komplette Konfiguration soll ueber eine GUI moeglich sein.
- Es gibt getrennte Sensoren fuer Netzbezug und Einspeisung, beide ohne Vorzeichen.
- Anker liefert getrennte Werte fuer PV-Eingangsleistung und Ausgangsleistung.
- Es gibt pro Anker-Geraet einen System-Akkustand.
- Der Akku soll ueber den Tag geladen werden, aber nur bis zu einem konfigurierbaren Zielwert, initial 80 Prozent.
- Wegen der 800-W-Ausgabebegrenzung der Solarbox sollen flexible Verbraucher fruehzeitig starten, wenn sonst Solarenergie ungenutzt bleibt.
- Ziel ist eine moeglichst hohe Eigenverbrauchsquote.
- Die Poolpumpe soll in einem konfigurierbaren Tagesfenster laufen und mindestens 8 Stunden pro Tag erreichen.
- Netzstrom ist fuer die Poolpumpe erlaubt, wenn mindestens 70 Prozent ihres Verbrauchs gedeckt sind oder wenn sie sonst die Tagesmindestlaufzeit nicht erreicht.
- Weitere Verbraucher, zuerst ein Entfeuchter, sollen spaeter priorisiert werden.
- Der Entfeuchter soll rein nach Energieueberschuss laufen, nicht nach Luftfeuchtigkeit.

## Offene Fragen

- Welche konkreten Entity-IDs sollen als erste Default-Auswahl vorgeschlagen werden?
- Welche Leistung hat die Poolpumpe realistisch im Betrieb?
- Wie viele Minuten Mindestlaufzeit am Stueck sind fuer die Poolpumpe sinnvoll?
- Sollen manuell eingeschaltete Verbraucher vom Bot weiter gesteuert werden oder bis zum naechsten Tag tabu sein?
- Soll die GUI direkt im Add-on laufen oder spaeter als eigenes Home-Assistant-Panel eingebunden werden?

## Naechster Schritt

Als naechstes sollte eine Beispielkonfiguration erstellt werden, die zwei Anker-Solix-Quellen, getrennte Netzbezugs- und Einspeisesensoren, die Poolpumpe und den Entfeuchter modelliert. Danach kann ein kleiner Python-Prototyp mit GUI entstehen, der Home-Assistant-States liest, aber im Dry-Run-Modus noch nichts schaltet. So kann die Entscheidungslogik mit echten Sensordaten beobachtet werden, bevor das Add-on aktiv in das Haus eingreift.
