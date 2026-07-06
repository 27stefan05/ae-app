"""Erzeugt einen Passwort-Hash zum Eintragen in die .env-Datei (ADMIN_PASSWORD_HASH)."""
import getpass

from werkzeug.security import generate_password_hash

if __name__ == '__main__':
    password = getpass.getpass('Neues Passwort eingeben: ')
    confirm = getpass.getpass('Passwort wiederholen: ')

    if not password:
        print('Passwort darf nicht leer sein.')
    elif password != confirm:
        print('Die beiden Eingaben stimmen nicht überein.')
    else:
        print('\nTrage diese Zeile in deine .env-Datei ein:')
        print(f'ADMIN_PASSWORD_HASH={generate_password_hash(password)}')
