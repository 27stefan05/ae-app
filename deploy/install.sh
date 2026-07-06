#!/bin/bash
# Richtet den Arbeitsschein-Kiosk auf einem frischen Ubuntu Server ein.
#
# Voraussetzungen, bevor dieses Skript laeuft:
#   - Ubuntu Server ist installiert
#   - Ein Benutzer "kwin" existiert bereits (oder KIOSK_USER unten anpassen)
#   - Dieses Projekt liegt bereits unter /opt/ae-app (z.B. per USB-Stick kopiert
#     oder "git clone", solange noch Internet verfuegbar ist)
#
# Aufruf: sudo ./deploy/install.sh
#
# Das Skript installiert die noetigen Pakete, richtet die Python-Umgebung ein,
# registriert die App als systemd-Service und richtet den automatischen
# Kiosk-Start (Autologin + labwc + Chromium + Bildschirmtastatur) ein.
# Was danach noch manuell zu tun bleibt, steht am Ende der Ausgabe.

set -euo pipefail

APP_DIR="/opt/ae-app"
KIOSK_USER="kwin"

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo ausfuehren: sudo ./deploy/install.sh"
    exit 1
fi

if [ ! -d "$APP_DIR" ]; then
    echo "Fehler: $APP_DIR existiert nicht. Projekt zuerst dorthin kopieren."
    exit 1
fi

if ! id "$KIOSK_USER" >/dev/null 2>&1; then
    echo "Fehler: Benutzer '$KIOSK_USER' existiert nicht. Anlegen mit:"
    echo "  sudo adduser $KIOSK_USER"
    exit 1
fi

echo "==> Installiere System-Pakete..."
apt update
apt install -y python3 python3-venv python3-pip \
    labwc seatd chromium-browser squeekboard

echo "==> Python-Umgebung einrichten..."
sudo -u "$KIOSK_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$KIOSK_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$KIOSK_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements-prod.txt"

if [ ! -f "$APP_DIR/.env" ]; then
    echo "==> Lege .env aus Vorlage an..."
    sudo -u "$KIOSK_USER" cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi

echo "==> systemd-Service fuer die App einrichten..."
cp "$APP_DIR/deploy/ae-app.service" /etc/systemd/system/ae-app.service
systemctl daemon-reload
systemctl enable ae-app
systemctl restart ae-app

echo "==> Kiosk-Autostart (labwc + Chromium + Bildschirmtastatur) einrichten..."
sudo -u "$KIOSK_USER" mkdir -p "/home/$KIOSK_USER/.config/labwc"
sudo -u "$KIOSK_USER" cp "$APP_DIR/deploy/labwc-autostart" "/home/$KIOSK_USER/.config/labwc/autostart"
chmod +x "/home/$KIOSK_USER/.config/labwc/autostart"

BASH_PROFILE="/home/$KIOSK_USER/.bash_profile"
AUTOSTART_LINE='[ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ] && exec labwc'
if ! grep -qF "$AUTOSTART_LINE" "$BASH_PROFILE" 2>/dev/null; then
    echo "$AUTOSTART_LINE" | sudo -u "$KIOSK_USER" tee -a "$BASH_PROFILE" > /dev/null
fi

echo "==> Automatischen Login auf tty1 fuer '$KIOSK_USER' einrichten..."
mkdir -p /etc/systemd/system/getty@tty1.service.d
sed "s/__KIOSK_USER__/$KIOSK_USER/" "$APP_DIR/deploy/tty1-autologin.conf" \
    > /etc/systemd/system/getty@tty1.service.d/override.conf
systemctl daemon-reload

echo ""
echo "================================================================"
echo "Fertig. Von Hand noch zu erledigen, bevor ihr neu startet:"
echo ""
echo "  1. Login-Passwort fuer /einstellungen setzen (schreibt automatisch in .env):"
echo "       cd $APP_DIR && sudo -u $KIOSK_USER venv/bin/python hash_password.py"
echo ""
echo "  2. Falls externe Backup-SSD vorhanden: deren Pfad als BACKUP_DIR"
echo "     in $APP_DIR/.env eintragen."
echo ""
echo "  3. Bildschirm-Rotation (Hochformat) und Standby-Abschaltung sind"
echo "     hardwareabhaengig und nicht Teil dieses Skripts - siehe deploy/README.md."
echo ""
echo "  4. sudo systemctl restart ae-app"
echo "  5. sudo reboot"
echo "================================================================"
