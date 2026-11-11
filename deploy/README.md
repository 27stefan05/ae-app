# Deployment auf dem Kiosk-Rechner (Ubuntu Server)

Diese Dateien richten die App als dauerhaft laufenden Kiosk auf einem
Touchscreen-Rechner ein: Gunicorn als Produktions-Server (systemd-Service),
Autologin + labwc (minimaler Wayland-Fenstermanager) + Chromium im Kiosk-Modus.
Die Bildschirmtastatur ist Teil der App (`static/osk.js`).

## Ablauf

1. Ubuntu Server **26.04 LTS** installieren, im Installer Tastaturlayout **German**
   waehlen und einen eigenen Admin-Benutzer anlegen. Danach `sudo adduser kwin`
   (Kiosk-Benutzer, ohne sudo-Rechte).
2. Dieses Projekt nach `/opt/ae-app` kopieren (per `git clone`, solange noch
   Internet verfuegbar ist, oder per USB-Stick).
3. `sudo ./deploy/install.sh` ausfuehren.
4. Die am Ende des Skripts angezeigten manuellen Schritte erledigen
   (Passwort setzen, ggf. `BACKUP_DIR`, siehe unten).
5. Neu starten.

## Was das Skript automatisiert

- System-Pakete (`labwc`, `seatd`, `wlr-randr`, `swaybg`, `curl`, `plymouth`, `chromium-browser`)
- Boot-Logo: Plymouth bis labwc steht, danach dasselbe Logo, bis die App auf Port 5000 antwortet
- Benutzer `kwin` in den Gruppen `video`, `render` und `input` (plus `seat`, falls vorhanden), `seatd` wird gestartet
- Python-venv + Abhaengigkeiten aus `requirements-prod.txt`
- systemd-Service `ae-app` (Gunicorn, startet automatisch, neu startet bei Absturz)
- Tastaturlayout Deutsch fuer eine angeschlossene Tastatur (`deploy/labwc-environment`)
- Kiosk-Autostart: Autologin auf tty1 fuer den `kwin`-Benutzer, der beim Login
  automatisch `labwc` startet, das wiederum Chromium im
  Kiosk-Modus startet (und Chromium bei einem Absturz automatisch neu startet)
- Bildschirm-Rotation ins Hochformat via `wlr-randr` (siehe `deploy/labwc-autostart`)

## Bildschirm-Rotation

`deploy/labwc-autostart` dreht beim Start jeden angeschlossenen Ausgang per
`wlr-randr --transform 270` ins Hochformat, der Anschlussname (DP, HDMI) spielt
keine Rolle. labwc hat dafuer keine eigene `rc.xml`-Option.

Steht das Bild auf dem Kopf, in `deploy/labwc-autostart` `270` durch `90`
ersetzen und `install.sh` erneut ausfuehren.

## Startbildschirm

Beim Einschalten kommt kein Boot-Text und kein Terminal. Zuerst das Plymouth-Logo,
danach dasselbe Logo im Kiosk, bis `http://127.0.0.1:5000/` antwortet. Erst dann
oeffnet Chromium die App. Die Farbe ist das Blau der Kopfzeile (`#0078DC`).

Das GRUB-Menue ist versteckt. Es erscheint, wenn man beim Einschalten **Esc**
(UEFI) oder die **linke Shift-Taste** (BIOS) haelt.

## Wartungsterminal

Autologin gilt nur fuer tty1. Eine Tastatur anschliessen:

| Taste | Wirkung |
|---|---|
| Strg+Alt+F2 | Login-Prompt. Mit dem Admin-Benutzer anmelden (`kwin` hat kein sudo und keinen Passwort-Login), nicht mit dem App-Passwort |
| Strg+Alt+F1 | zurueck zum Kiosk |

Das geht auch schon, waehrend das Logo laeuft. Ohne Tastatur kommt man vom
Touchscreen aus nicht auf die Konsole. Wenn labwc nicht startet, verschwindet
das Logo nach zwei Minuten von selbst.

## Was bewusst nicht automatisiert ist (hardware-/ortsabhaengig)

- **Bildschirm-Standby**: das System schaltet den Bildschirm nicht ab. Eine
  automatische Abschaltung (Auto-Standby, Eco) ist eine Einstellung im Menue
  des Monitors und dort auszuschalten.
- **Chromium via Snap**: Ubuntu installiert `chromium-browser` standardmaessig
  als Snap-Paket, das beim ersten `apt install` aus dem Internet nachgeladen
  wird. Ist waehrend der Einrichtung kein Internet verfuegbar, muss Chromium
  vorher anders beschafft werden (z.B. Snap-Datei separat herunterladen und
  offline installieren, oder eine Firefox-Kiosk-Alternative pruefen).

## Nuetzliche Befehle zum Nachschauen

```
sudo systemctl status ae-app       # laeuft der App-Server?
sudo journalctl -u ae-app -f       # Logs der App live verfolgen
sudo systemctl restart ae-app      # nach Aenderungen an .env neu laden
```

## Update ohne Netz (USB-Stick)

Auf einem Rechner mit Internet den aktuellen Stand als eine Datei auf den Stick
legen (ein Ordner mit `.git` geht nicht: auf dem Stick gehoeren die Dateien
root, und git verweigert dann den Zugriff):

```
git clone https://github.com/27stefan05/ae-app.git && cd ae-app
git bundle create /pfad/zum/stick/ae-app.bundle main
```

Am Kiosk als Admin-Benutzer:

```
cd /opt/ae-app
sudo -u kwin git pull /media/<stick>/ae-app.bundle main
sudo bash deploy/install.sh
```

`install.sh` nach jedem Update ausfuehren, es uebernimmt auch geaenderte
Dienst- und Autostart-Dateien und startet die App neu. Ohne Netz laesst es die
vorhandene Python-Umgebung stehen. Nur wenn sich `requirements-prod.txt`
geaendert hat, die Pakete vorher mit
`pip download -r requirements-prod.txt -d ae-app-wheels` auf den Stick holen und
`sudo WHEELS=/media/<stick>/ae-app-wheels bash deploy/install.sh` aufrufen.

## Uhrzeit

Der Kiosk hat im Betrieb kein Netz und stellt die Uhr nicht selbst. Zeitzone ist
`Europe/Berlin`. Bei jedem Update die Uhr pruefen (`date`) und bei Bedarf stellen:
`sudo timedatectl set-time 'JJJJ-MM-TT HH:MM:SS'`. Backups und PDFs behalten immer
die 30 neuesten Dateien, ein Sprung der Uhr loescht also nicht alles.
