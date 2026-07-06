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

- System-Pakete (`labwc`, `chromium-browser`, `squeekboard`, ...)
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
