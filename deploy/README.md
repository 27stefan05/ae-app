# Deployment auf dem Kiosk-Rechner (Ubuntu Server)

Diese Dateien richten die App als dauerhaft laufenden Kiosk auf einem
Touchscreen-Rechner ein: Gunicorn als Produktions-Server (systemd-Service),
Autologin + labwc (minimaler Wayland-Fenstermanager) + Chromium im Kiosk-Modus
+ Squeekboard als Bildschirmtastatur.

## Ablauf

1. Ubuntu Server installieren, Benutzer `kwin` anlegen.
2. Dieses Projekt nach `/opt/ae-app` kopieren (per `git clone`, solange noch
   Internet verfuegbar ist, oder per USB-Stick).
3. `sudo ./deploy/install.sh` ausfuehren.
4. Die am Ende des Skripts angezeigten manuellen Schritte erledigen
   (Passwort setzen, ggf. `BACKUP_DIR`, siehe unten).
5. Neu starten.

## Was das Skript automatisiert

- System-Pakete (`labwc`, `seatd`, `wlr-randr`, `swaybg`, `curl`, `plymouth`, `chromium-browser`, `squeekboard`)
- Boot-Logo: Plymouth bis labwc steht, danach dasselbe Logo, bis die App auf Port 5000 antwortet
- Benutzer `kwin` in den Gruppen `video`, `render` und `input` (plus `seat`, falls vorhanden), `seatd` wird gestartet
- Python-venv + Abhaengigkeiten aus `requirements-prod.txt`
- systemd-Service `ae-app` (Gunicorn, startet automatisch, neu startet bei Absturz)
- Kiosk-Autostart: Autologin auf tty1 fuer den `kwin`-Benutzer, der beim Login
  automatisch `labwc` startet, das wiederum Squeekboard und Chromium im
  Kiosk-Modus startet (und Chromium bei einem Absturz automatisch neu startet)
- Bildschirm-Rotation ins Hochformat via `wlr-randr` (siehe `deploy/labwc-autostart`)

## Bildschirm-Rotation auf anderer Hardware anpassen

`deploy/labwc-autostart` ruft beim Start `wlr-randr --output DP-1 --transform 270`
auf. Diese Werte sind hardwareabhaengig und wurden fuer das aktuelle Geraet
ermittelt - labwc hat dafuer keine eigene `rc.xml`-Option, `wlr-randr` im
Autostart-Kontext von labwc funktioniert aber zuverlaessig (im Gegensatz zu
einem manuellen Aufruf von aussen, der an der Wayland-Umgebung scheitert).

Auf neuer/anderer Hardware den Ausgabenamen so ermitteln:
```
ls /sys/class/drm/
cat /sys/class/drm/*/status
```
Der Name kann trotz HDMI-Kabel z.B. `DP-1` lauten, wenn der physische Port
intern per DP++ (Dual-Mode DisplayPort) umgesetzt wird - das ist normal.
Bei falscher Drehrichtung `--transform 90` statt `270` (oder umgekehrt)
probieren, dann `deploy/labwc-autostart` entsprechend anpassen.

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
| Strg+Alt+F2 | Login-Prompt. Benutzer `kwin` und das Ubuntu-Passwort, nicht das App-Passwort |
| Strg+Alt+F1 | zurueck zum Kiosk |

Das geht auch schon, waehrend das Logo laeuft. Ohne Tastatur kommt man vom
Touchscreen aus nicht auf die Konsole. Wenn labwc nicht startet, verschwindet
das Logo nach zwei Minuten von selbst.

## Was bewusst nicht automatisiert ist (hardware-/ortsabhaengig)

- **Bildschirm-Standby verhindern**: der Touchscreen darf nie in den
  Energiesparmodus gehen. Je nach Compositor-Version z.B. per `wlopm` oder
  einer entsprechenden labwc-Einstellung - am Geraet selbst pruefen, ob/wann
  der Bildschirm dunkel wird, und danach gezielt abschalten.
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
