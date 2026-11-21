#!/bin/bash
# Setzt ein GRUB-Passwort fuer den Kiosk.
#
# Danach startet der Kiosk weiter ohne Eingabe. Nur wer beim Start etwas
# aendern will (Taste e, Konsole c), braucht Benutzer "grubadmin" und das
# Passwort. Der Wiederherstellungsmodus wird abgeschaltet, weil er sonst eine
# root-Konsole ohne Passwort oeffnet.
#
# Aufruf:  sudo bash deploy/grub-password.sh
# Zurueck: sudo bash deploy/grub-password.sh --entfernen
#
# GRUB nutzt die englische Tastatur. Deshalb sind nur Kleinbuchstaben ohne
# y und z sowie Ziffern erlaubt, die liegen auf beiden Tastaturen gleich.

set -euo pipefail

GRUB_USER="grubadmin"
GRUB_D="${GRUB_D:-/etc/grub.d}"
DEFAULT_GRUB="${DEFAULT_GRUB:-/etc/default/grub}"
GRUB_CFG="${GRUB_CFG:-/boot/grub/grub.cfg}"
UPDATE_GRUB="${UPDATE_GRUB:-update-grub}"
PW_FILE="$GRUB_D/01_kiosk_password"
LINUX_FILE="$GRUB_D/10_linux"
CLASS_OLD='CLASS="--class gnu-linux --class gnu --class os"'
CLASS_NEW='CLASS="--class gnu-linux --class gnu --class os --unrestricted"'

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo ausfuehren: sudo bash deploy/grub-password.sh"
    exit 1
fi

set_recovery() {
    # $1: true oder false
    if grep -q '^GRUB_DISABLE_RECOVERY=' "$DEFAULT_GRUB"; then
        sed -i "s/^GRUB_DISABLE_RECOVERY=.*/GRUB_DISABLE_RECOVERY=\"$1\"/" "$DEFAULT_GRUB"
    else
        echo "GRUB_DISABLE_RECOVERY=\"$1\"" >> "$DEFAULT_GRUB"
    fi
}

remove_password() {
    rm -f "$PW_FILE"
    sed -i "s/^$CLASS_NEW\$/$CLASS_OLD/" "$LINUX_FILE"
    set_recovery false
}

if [ "${1:-}" = "--entfernen" ]; then
    remove_password
    "$UPDATE_GRUB"
    echo ""
    echo "GRUB-Passwort entfernt."
    exit 0
fi

# Nur weitermachen, wenn 10_linux so aussieht wie erwartet. Sonst wuerde der
# normale Start nach dem Passwort fragen und der Kiosk bliebe stehen.
if ! grep -qxF "$CLASS_OLD" "$LINUX_FILE" && ! grep -qxF "$CLASS_NEW" "$LINUX_FILE"; then
    echo "Abbruch: $LINUX_FILE sieht anders aus als erwartet, nichts geaendert."
    echo "Gesucht wurde die Zeile: $CLASS_OLD"
    exit 1
fi

echo "GRUB-Passwort festlegen."
echo "Erlaubt: Kleinbuchstaben ohne y und z, Ziffern. Mindestens 8 Zeichen."
echo "Vorher aufschreiben! Benutzername in GRUB: $GRUB_USER"
echo ""
while true; do
    read -r -s -p "GRUB-Passwort: " PW; echo
    read -r -s -p "Nochmal:       " PW2; echo
    if [ "$PW" != "$PW2" ]; then
        echo "Die beiden Eingaben sind verschieden, bitte nochmal."
    elif [ "${#PW}" -lt 8 ]; then
        echo "Zu kurz, mindestens 8 Zeichen."
    elif ! [[ "$PW" =~ ^[a-x0-9]+$ ]]; then
        echo "Nur Kleinbuchstaben a-x und Ziffern (kein y, z, keine Grossbuchstaben oder Sonderzeichen)."
    else
        break
    fi
done

HASH=$(printf '%s\n%s\n' "$PW" "$PW" | grub-mkpasswd-pbkdf2 | grep -o 'grub\.pbkdf2\.sha512\.[^ ]*' || true)
unset PW PW2
if [ -z "$HASH" ]; then
    echo "Abbruch: Passwort-Hash konnte nicht erzeugt werden, nichts geaendert."
    exit 1
fi

umask 077
cat > "$PW_FILE" << EOF
#!/bin/sh
# Vom Kiosk-Skript deploy/grub-password.sh angelegt.
cat << 'GRUB'
set superusers="$GRUB_USER"
password_pbkdf2 $GRUB_USER $HASH
GRUB
EOF
chmod 700 "$PW_FILE"

sed -i "s/^$CLASS_OLD\$/$CLASS_NEW/" "$LINUX_FILE"
set_recovery true

if ! "$UPDATE_GRUB"; then
    echo "Abbruch: update-grub fehlgeschlagen, Aenderungen werden zurueckgenommen."
    remove_password
    "$UPDATE_GRUB" || true
    exit 1
fi

# Pruefen: Passwort aktiv und normaler Start ohne Abfrage.
if ! grep -q "^set superusers=\"$GRUB_USER\"" "$GRUB_CFG" \
    || ! grep -q '^menuentry .*--unrestricted' "$GRUB_CFG"; then
    echo "Abbruch: Ergebnis in $GRUB_CFG stimmt nicht, Aenderungen werden zurueckgenommen."
    remove_password
    "$UPDATE_GRUB" || true
    exit 1
fi

echo ""
echo "================================================================"
echo "GRUB-Passwort ist gesetzt."
echo "  Benutzer: $GRUB_USER"
echo "Der Kiosk startet weiter ohne Eingabe. Zum Testen:"
echo "  sudo reboot, beim Start Esc druecken, bei Ubuntu die Taste e."
echo "  Dann muss GRUB nach Benutzer und Passwort fragen."
echo "Entfernen: sudo bash deploy/grub-password.sh --entfernen"
echo "================================================================"
