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

# Die App laeuft als $KIOSK_USER und schreibt in instance/ und static/.
# Wurde das Projekt als root kopiert oder geklont, klappt sonst schon venv nicht.
chown -R "$KIOSK_USER:$KIOSK_USER" "$APP_DIR"

echo "==> Installiere System-Pakete..."
apt update
apt install -y python3 python3-venv python3-pip \
    labwc seatd wlr-randr swaybg curl plymouth chromium-browser squeekboard

echo "==> Gruppen und seatd fuer den Kiosk-Benutzer..."
# video/render: Bildschirm und GPU, input: Touch und Tastatur.
# seat nur, wenn das Paket die Gruppe anlegt. Wirkt erst nach dem naechsten Login.
KIOSK_GROUPS="video,render,input"
if getent group seat >/dev/null; then
    KIOSK_GROUPS="$KIOSK_GROUPS,seat"
fi
usermod -aG "$KIOSK_GROUPS" "$KIOSK_USER"
systemctl enable --now seatd

echo "==> Boot-Logo (Plymouth) einrichten..."
THEME_DIR="/usr/share/plymouth/themes/ae-splash"
rm -rf "$THEME_DIR"
mkdir -p "$THEME_DIR"
cp "$APP_DIR/deploy/plymouth/ae-splash.plymouth" \
   "$APP_DIR/deploy/plymouth/ae-splash.script" \
   "$APP_DIR/deploy/plymouth/logo.png" \
   "$THEME_DIR/"
# -R schreibt das Theme in die Initramfs, sonst sieht man es beim Start nicht.
plymouth-set-default-theme -R ae-splash

python3 - << 'PY'
from pathlib import Path
path = Path("/etc/default/grub")
text = path.read_text() if path.exists() else ""
wanted = {
    "GRUB_CMDLINE_LINUX_DEFAULT": '"quiet splash loglevel=3 systemd.show_status=false"',
    "GRUB_TIMEOUT_STYLE": "hidden",
    "GRUB_TIMEOUT": "0",
}
seen = set()
out = []
for line in text.splitlines():
    stripped = line.strip()
    key = stripped.split("=", 1)[0] if stripped and not stripped.startswith("#") and "=" in stripped else None
    if key in wanted:
        out.append(f"{key}={wanted[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in wanted.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n")
PY
update-grub

mkdir -p /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/kiosk-quiet.conf << 'EOF'
[Manager]
ShowStatus=no
EOF

# Plymouth nicht schon am Login-Prompt beenden. labwc macht das, sobald
# das Logo im Fenster steht. Falls labwc haengt, gibt es nach 2 Minuten frei.
mkdir -p /etc/systemd/system/plymouth-quit.service.d
cat > /etc/systemd/system/plymouth-quit.service.d/kiosk.conf << 'EOF'
[Service]
ExecStart=
ExecStart=/bin/true
EOF
cat > /etc/systemd/system/kiosk-plymouth-failsafe.service << 'EOF'
[Unit]
Description=Plymouth beenden, falls der Kiosk nicht uebernimmt
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'sleep 120; plymouth quit || true'

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable kiosk-plymouth-failsafe.service

# tty2 bleibt ein normales Login fuer die Wartung. Autologin gilt nur fuer tty1.
systemctl enable getty@tty2.service


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
echo ""
echo "Wartung, wenn der Kiosk laeuft (USB-Tastatur):"
echo "  Strg+Alt+F2  ->  Login mit dem Ubuntu-Benutzer kwin und dessen Passwort"
echo "  Strg+Alt+F1  ->  zurueck zum Kiosk"
echo "  Das Passwort der App unter /einstellungen gilt hier nicht."
echo "  GRUB-Menue: beim Einschalten Esc (UEFI) oder linke Shift-Taste (BIOS) halten."
echo "================================================================"
