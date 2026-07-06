"""Erzeugt einen Passwort-Hash und traegt ihn direkt in die .env-Datei ein (ADMIN_PASSWORD_HASH)."""
import getpass
import os
import sys

from werkzeug.security import generate_password_hash

DEFAULT_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')


def upsert_env_value(env_path, key, value):
    """Setzt key=value in der .env-Datei - ersetzt eine vorhandene Zeile oder haengt sie an."""
    line = f'{key}={value}'
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()

    for i, existing in enumerate(lines):
        if existing.strip().startswith(f'{key}='):
            lines[i] = line + '\n'
            break
    else:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(line + '\n')

    with open(env_path, 'w') as f:
        f.writelines(lines)


def main():
    password = getpass.getpass('Neues Passwort eingeben: ')
    confirm = getpass.getpass('Passwort wiederholen: ')

    if not password:
        print('Passwort darf nicht leer sein.')
        return 1
    if password != confirm:
        print('Die beiden Eingaben stimmen nicht überein.')
        return 1

    password_hash = generate_password_hash(password)
    upsert_env_value(DEFAULT_ENV_PATH, 'ADMIN_PASSWORD_HASH', password_hash)
    print(f'\nPasswort gespeichert in {DEFAULT_ENV_PATH}.')
    print('Falls die App bereits laeuft: sudo systemctl restart ae-app')
    return 0


if __name__ == '__main__':
    sys.exit(main())
