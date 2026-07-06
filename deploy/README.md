# Deployment auf dem Kiosk-Rechner (Ubuntu Server)

Diese Dateien richten die App als dauerhaft laufenden Kiosk auf einem
Touchscreen-Rechner ein: Gunicorn als Produktions-Server (systemd-Service),
Autologin + labwc (minimaler Wayland-Fenstermanager) + Chromium im Kiosk-Modus
+ Squeekboard als Bildschirmtastatur.

## Ablauf

1. Ubuntu Server installieren, Benutzer `kiosk` anlegen.
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
- Kiosk-Autostart: Autologin auf tty1 fuer den `kiosk`-Benutzer, der beim Login
  automatisch `labwc` startet, das wiederum Squeekboard und Chromium im
  Kiosk-Modus startet (und Chromium bei einem Absturz automatisch neu startet)

## Was bewusst nicht automatisiert ist (hardware-/ortsabhaengig)

- **Bildschirm-Rotation ins Hochformat**: haengt vom genutzten Grafiktreiber
  und Ausgabename ab. Unter labwc in `~/.config/labwc/rc.xml` fuer den
  jeweiligen `<output>` ein `transform="90"` (oder `270`, je nach
  Einbaurichtung) ergaenzen.
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
