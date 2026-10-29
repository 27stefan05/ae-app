from flask import Flask, request, jsonify, render_template, redirect, url_for, send_from_directory, session, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
import os
import re
import atexit
import threading
import secrets
import sqlite3
import shutil
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.units import cm

load_dotenv(interpolate=False)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'scheine.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

BACKUP_DIR = os.environ.get('BACKUP_DIR')
BACKUP_RETENTION_DAYS = 30

os.makedirs(app.instance_path, exist_ok=True)
secret_key_path = os.path.join(app.instance_path, 'secret_key.txt')
if os.environ.get('SECRET_KEY'):
    app.secret_key = os.environ['SECRET_KEY']
elif os.path.exists(secret_key_path):
    with open(secret_key_path) as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    with open(secret_key_path, 'w') as f:
        f.write(app.secret_key)

DEFAULT_ADMIN_PASSWORD_HASH = generate_password_hash('test')
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH', DEFAULT_ADMIN_PASSWORD_HASH)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ===================== MODELLE =====================
class Arbeitsschein(db.Model):
    __tablename__ = 'arbeitsschein'
    id = db.Column(db.Integer, primary_key=True)
    ae_nummer = db.Column(db.String(20), nullable=False)
    personen = db.Column(db.Integer, default=0)
    firma = db.Column(db.String(100))
    ort = db.Column(db.String(100))
    telefonnummer = db.Column(db.String(20))
    fach = db.Column(db.Integer, default=0)
    beschreibung = db.Column(db.String(200))
    ausgabedatum = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    rueckgabedatum = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='ausgegeben')
    bemerkung = db.Column(db.String(500), nullable=True)
    vorgang = db.Column(db.Integer, default=10)

    __table_args__ = (db.UniqueConstraint('ae_nummer', 'vorgang', name='_ae_vorgang_uc'),)

class Ort(db.Model):
    __tablename__ = 'ort'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)

class Firma(db.Model):
    __tablename__ = 'firma'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)

class Setting(db.Model):
    __tablename__ = 'setting'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True)
    value = db.Column(db.String(50))

# ===================== HILFSFUNKTIONEN =====================
# Grenzen für Eingaben. SQLite prüft Längen nicht selbst, und zu große Zahlen
# oder Texte führen sonst zu Serverfehlern oder sprengen das Tages-PDF.
MAX_MAPPEN_LIMIT = 2000
MAX_VORGAENGE_LIMIT = 990
MAX_VORGANG = 9990
MAX_PERSONEN = 999
MAX_LEN = {'firma': 100, 'ort': 100, 'telefonnummer': 20, 'bemerkung': 500}
AE_PATTERN = re.compile(r'^\d{1,8}$')

# Anlegen, Löschen und Wiederherstellen laufen nacheinander, damit zwei
# gleichzeitige Anfragen nicht dieselbe freie Mappe bekommen (1 Gunicorn-Worker).
schein_lock = threading.Lock()


def get_int_setting(key, default, low, high):
    """Zahl aus den Einstellungen; bei kaputtem Wert der Standard, sonst begrenzt."""
    setting = Setting.query.filter_by(key=key).first()
    try:
        value = int(setting.value) if setting else default
    except (TypeError, ValueError):
        value = default
    return min(max(value, low), high)


def get_max_mappen():
    return get_int_setting('max_mappen', 300, 1, MAX_MAPPEN_LIMIT)

def get_next_fach():
    """Kleinste freie Mappe oder None, wenn alle belegt sind.

    Eine Mappe wird erst frei, wenn der Schein gelöscht ist."""
    used = {s.fach for s in Arbeitsschein.query.all()}
    for i in range(1, get_max_mappen() + 1):
        if i not in used:
            return i
    return None

def get_fach_for_ae(ae_nummer):
    """Mappe, in der die AE-Nummer schon liegt, sonst None.

    Alle Vorgänge einer AE-Nummer kommen in dieselbe Mappe."""
    if not ae_nummer:
        return None
    schein = Arbeitsschein.query.filter_by(ae_nummer=ae_nummer).first()
    return schein.fach if schein else None

def get_next_vorgang(ae_nummer):
    """Kleinster freie Vorgang (10, 20, ...) für diese AE-Nummer."""
    used = {s.vorgang for s in Arbeitsschein.query.filter_by(ae_nummer=ae_nummer)}
    vorgang = 10
    while vorgang in used:
        vorgang += 10
    return vorgang

def mappen_voll_meldung():
    return (f"Alle {get_max_mappen()} Mappen sind belegt. Bitte erst einen fertigen Schein "
            "löschen oder die maximale Anzahl Mappen in den Einstellungen erhöhen.")

# Standort des Kiosks. Der Dark Mode schaltet nach Sonnenaufgang und
# Sonnenuntergang an diesem Ort. Fest eingestellt, der Kiosk zieht nicht um.
THEME_LAT = 48.76071585556061
THEME_LON = 11.502540053417018


def upsert_setting(key, value):
    setting = Setting.query.filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        db.session.add(Setting(key=key, value=value))


@app.context_processor
def inject_theme_coords():
    return {'theme_lat': THEME_LAT, 'theme_lon': THEME_LON}


def get_max_vorgaenge():
    return get_int_setting('max_vorgaenge', 200, 10, MAX_VORGAENGE_LIMIT)

def get_vorgang_options(max_vorgaenge):
    return list(range(10, max_vorgaenge + 10, 10))

def parse_int(value, field_name, minimum=None, maximum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} muss eine Zahl sein.")
    if minimum is not None and result < minimum:
        raise ValueError(f"{field_name} muss mindestens {minimum} sein.")
    if maximum is not None and result > maximum:
        raise ValueError(f"{field_name} darf höchstens {maximum} sein.")
    return result


def normalize_ae(value):
    """AE-Nummer ohne Leerzeichen; erlaubt sind 1 bis 8 Ziffern."""
    ae = re.sub(r'\s+', '', value or '')
    if ae and not AE_PATTERN.match(ae):
        raise ValueError("Die AE-Nummer darf nur aus Ziffern bestehen (höchstens 8).")
    return ae


def text_fields(data):
    """Firma, Ort, Telefon, Bemerkung: getrimmt und auf Spaltenlänge geprüft."""
    labels = {'firma': 'Firma', 'ort': 'Ort', 'telefonnummer': 'Telefonnummer', 'bemerkung': 'Bemerkung'}
    values = {}
    for key, limit in MAX_LEN.items():
        value = (data.get(key) or '').strip()
        if len(value) > limit:
            raise ValueError(f"{labels[key]} darf höchstens {limit} Zeichen lang sein.")
        values[key] = value
    return values

STATUS_VALUES = {'ausgegeben', 'in arbeit', 'zurueckgegeben'}
SESSION_TIMEOUT_SECONDS = 900


def session_state():
    """'ok', 'anon' oder 'timeout'. Bei gültiger Sitzung wird die Aktivität erneuert."""
    if not session.get('logged_in'):
        return 'anon'
    last_raw = session.get('last_activity')
    if last_raw:
        try:
            last = datetime.fromisoformat(last_raw)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last).total_seconds() > SESSION_TIMEOUT_SECONDS:
                session.clear()
                return 'timeout'
        except ValueError:
            session.clear()
            return 'timeout'
    session['last_activity'] = datetime.now(timezone.utc).isoformat()
    return 'ok'


def require_login():
    if session_state() != 'ok':
        return jsonify({'error': 'Nicht angemeldet'}), 401
    return None


def eingabe_form_values():
    src = request.form if request.method == 'POST' and request.form else request.args
    return {
        'ae_nummer': (src.get('ae_nummer') or '').strip(),
        'vorgang': src.get('vorgang') or '10',
        'personen': src.get('personen') or '1',
        'telefonnummer': src.get('telefonnummer') or '',
        'bemerkung': src.get('bemerkung') or '',
        'firma': src.get('preselect_firma') or src.get('firma') or '',
        'ort': src.get('preselect_ort') or src.get('ort') or '',
    }


def edit_draft(schein, source, preselect_firma=None, preselect_ort=None):
    def picked(key, fallback):
        if source is not None and key in source:
            return source.get(key)
        return fallback

    raw_vorgang = picked('vorgang', schein.vorgang)
    try:
        selected_vorgang = int(raw_vorgang)
    except (TypeError, ValueError):
        selected_vorgang = schein.vorgang

    return {
        'selected_firma': preselect_firma or picked('firma', schein.firma) or '',
        'selected_ort': preselect_ort or picked('ort', schein.ort) or '',
        'selected_vorgang': selected_vorgang,
        'draft_personen': picked('personen', schein.personen),
        'draft_telefon': picked('telefonnummer', schein.telefonnummer or ''),
        'draft_bemerkung': picked('bemerkung', schein.bemerkung or ''),
    }

DOUBLE_SUBMIT_SECONDS = 15


def is_same_recent_schein(schein, personen, texts):
    """Wurde genau dieser Schein gerade eben angelegt (Doppeltipp auf Speichern)?"""
    if not schein.ausgabedatum:
        return False
    created = schein.ausgabedatum
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - created).total_seconds() > DOUBLE_SUBMIT_SECONDS:
        return False
    return schein.personen == personen and all(
        (getattr(schein, key) or '') == value for key, value in texts.items())

# ===================== ROUTEN =====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scheine')
def get_scheine():
    scheine = Arbeitsschein.query.all()
    return jsonify([{
        'id': s.id,
        'ae_nummer': s.ae_nummer,
        'vorgang': s.vorgang,
        'fach': s.fach,
        'firma': s.firma or '',
        'ort': s.ort or '',
        'personen': s.personen,
        'telefonnummer': s.telefonnummer or '',
        'status': s.status,
        'bemerkung': s.bemerkung or ''
    } for s in scheine])

@app.route('/eingabe', methods=['GET', 'POST'])
def eingabe():
    # Neue Firma/Ort automatisch anlegen, wenn per Redirect übergeben
    preselect_firma = request.args.get('preselect_firma')
    if preselect_firma:
        if not Firma.query.filter_by(name=preselect_firma).first():
            db.session.add(Firma(name=preselect_firma))
            db.session.commit()

    preselect_ort = request.args.get('preselect_ort')
    if preselect_ort:
        if not Ort.query.filter_by(name=preselect_ort).first():
            db.session.add(Ort(name=preselect_ort))
            db.session.commit()

    if request.method == 'POST':
        data = request.form
        raw_ae = (data.get('ae_nummer') or '').strip()

        def render_error(message):
            max_vorgaenge = get_max_vorgaenge()
            free_fach = get_next_fach()
            try:
                current_fach = get_fach_for_ae(normalize_ae(raw_ae))
            except ValueError:
                current_fach = None
            return render_template('eingabe.html', error=message,
                                   values=eingabe_form_values(),
                                   max_vorgaenge=max_vorgaenge, vorgang_options=get_vorgang_options(max_vorgaenge),
                                   next_fach=current_fach or free_fach,
                                   free_fach=free_fach,
                                   orte=Ort.query.order_by(func.lower(Ort.name).asc()).all(),
                                   firmen=Firma.query.order_by(func.lower(Firma.name).asc()).all())

        try:
            ae_nummer = normalize_ae(raw_ae)
            if not ae_nummer:
                raise ValueError("AE-Nummer darf nicht leer sein.")
            vorgang = parse_int(data.get('vorgang', 10), 'Vorgang', minimum=10, maximum=MAX_VORGANG)
            personen = parse_int(data.get('personen') or 0, 'Anzahl Mitarbeiter', minimum=0, maximum=MAX_PERSONEN)
            texts = text_fields(data)
        except ValueError as e:
            return render_error(str(e))

        with schein_lock:
            existing = Arbeitsschein.query.filter_by(ae_nummer=ae_nummer, vorgang=vorgang).first()
            if existing:
                # Doppelt abgeschickt (zweimal getippt): den eben angelegten Schein zeigen.
                if is_same_recent_schein(existing, personen, texts):
                    return redirect(url_for('index', neu=existing.id))
                return render_error("Diese AE-Nummer mit diesem Vorgang existiert bereits!")

            # Die Mappe bestimmt immer der Server. Weiterer Vorgang einer
            # vorhandenen AE: deren Mappe; neue AE: die kleinste freie.
            fach = get_fach_for_ae(ae_nummer) or get_next_fach()
            if fach is None:
                return render_error(mappen_voll_meldung())

            if texts['firma'] and not Firma.query.filter_by(name=texts['firma']).first():
                db.session.add(Firma(name=texts['firma']))
            if texts['ort'] and not Ort.query.filter_by(name=texts['ort']).first():
                db.session.add(Ort(name=texts['ort']))

            schein = Arbeitsschein(
                ae_nummer=ae_nummer,
                vorgang=vorgang,
                personen=personen,
                fach=fach,
                status='ausgegeben',
                **texts
            )
            db.session.add(schein)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                return render_error("Diese AE-Nummer mit diesem Vorgang existiert bereits!")

        # Startseite zeigt dann an, in welche Mappe der Schein gehört.
        return redirect(url_for('index', neu=schein.id))

    max_vorgaenge = get_max_vorgaenge()
    values = eingabe_form_values()
    try:
        values['ae_nummer'] = normalize_ae(values['ae_nummer'])
    except ValueError:
        values['ae_nummer'] = ''
    free_fach = get_next_fach()
    next_fach = get_fach_for_ae(values['ae_nummer']) or free_fach
    # Von der Startseite mit vorhandener AE: nächsten freien Vorgang vorschlagen.
    if values['ae_nummer'] and 'vorgang' not in request.args:
        values['vorgang'] = str(get_next_vorgang(values['ae_nummer']))
    orte = Ort.query.order_by(func.lower(Ort.name).asc()).all()
    firmen = Firma.query.order_by(func.lower(Firma.name).asc()).all()
    return render_template('eingabe.html', next_fach=next_fach, free_fach=free_fach, orte=orte, firmen=firmen,
                           error=None if next_fach else mappen_voll_meldung(),
                           values=values,
                           max_vorgaenge=max_vorgaenge, vorgang_options=get_vorgang_options(max_vorgaenge))

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    schein = Arbeitsschein.query.get_or_404(id)

    # Neue Firma/Ort automatisch anlegen, wenn per Redirect übergeben
    preselect_firma = request.args.get('preselect_firma')
    if preselect_firma:
        if not Firma.query.filter_by(name=preselect_firma).first():
            db.session.add(Firma(name=preselect_firma))
            db.session.commit()

    preselect_ort = request.args.get('preselect_ort')
    if preselect_ort:
        if not Ort.query.filter_by(name=preselect_ort).first():
            db.session.add(Ort(name=preselect_ort))
            db.session.commit()

    if request.method == 'POST':
        data = request.form

        def render_error(message):
            orte = Ort.query.order_by(func.lower(Ort.name).asc()).all()
            firmen = Firma.query.order_by(func.lower(Firma.name).asc()).all()
            max_vorgaenge = get_max_vorgaenge()
            return render_template('edit.html', schein=schein, orte=orte, firmen=firmen,
                                   max_vorgaenge=max_vorgaenge, vorgang_options=get_vorgang_options(max_vorgaenge),
                                   error=message, **edit_draft(schein, data))

        try:
            personen = parse_int(data.get('personen') or 0, 'Anzahl Mitarbeiter', minimum=0, maximum=MAX_PERSONEN)
            vorgang = parse_int(data.get('vorgang', schein.vorgang), 'Vorgang', minimum=10, maximum=MAX_VORGANG)
            texts = text_fields(data)
        except ValueError as e:
            return render_error(str(e))

        # Vor dem Ändern prüfen: sonst schreibt SQLAlchemy die Änderung bei der
        # nächsten Abfrage schon weg und es gibt einen Serverfehler statt Meldung.
        clash = Arbeitsschein.query.filter(
            Arbeitsschein.ae_nummer == schein.ae_nummer,
            Arbeitsschein.vorgang == vorgang,
            Arbeitsschein.id != schein.id,
        ).first()
        if clash:
            return render_error("Diese AE-Nummer mit diesem Vorgang existiert bereits!")

        with db.session.no_autoflush:
            if texts['firma'] and not Firma.query.filter_by(name=texts['firma']).first():
                db.session.add(Firma(name=texts['firma']))
            if texts['ort'] and not Ort.query.filter_by(name=texts['ort']).first():
                db.session.add(Ort(name=texts['ort']))
            schein.personen = personen
            schein.vorgang = vorgang
            for key, value in texts.items():
                setattr(schein, key, value)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return render_error("Diese AE-Nummer mit diesem Vorgang existiert bereits!")

        return redirect('/')

    orte = Ort.query.order_by(func.lower(Ort.name).asc()).all()
    firmen = Firma.query.order_by(func.lower(Firma.name).asc()).all()
    max_vorgaenge = get_max_vorgaenge()
    return render_template('edit.html', schein=schein, orte=orte, firmen=firmen, max_vorgaenge=max_vorgaenge,
                           vorgang_options=get_vorgang_options(max_vorgaenge),
                           **edit_draft(schein, request.args, preselect_firma, preselect_ort))

@app.route('/status/<int:id>', methods=['PUT'])
def change_status(id):
    schein = Arbeitsschein.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in STATUS_VALUES:
        return jsonify({'error': 'Ungültiger Status'}), 400
    schein.status = status
    if status == 'zurueckgegeben':
        schein.rueckgabedatum = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'message': 'Status geändert'})

# Gelöschte Scheine bleiben kurz im Speicher, damit "Rückgängig" geht.
# Die Oberfläche bietet das 10 Sekunden an, der Server hält etwas länger.
# Schlüssel ist ein Zufallswert, nicht die Datenbank-ID: SQLite vergibt IDs
# gelöschter Zeilen neu. Nach einem Neustart ist die Liste leer, das ist gewollt.
UNDO_SECONDS = 60
recently_deleted = {}


def forget_old_deletions():
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=UNDO_SECONDS)
    for key, (deleted_at, _) in list(recently_deleted.items()):
        if deleted_at < cutoff:
            recently_deleted.pop(key, None)


@app.route('/delete/<int:id>', methods=['DELETE'])
def delete_schein(id):
    with schein_lock:
        schein = db.session.get(Arbeitsschein, id)
        if not schein:
            return jsonify({'error': 'Arbeitsschein nicht gefunden'}), 404
        columns = {c.name: getattr(schein, c.name) for c in Arbeitsschein.__table__.columns if c.name != 'id'}
        db.session.delete(schein)
        db.session.commit()
        forget_old_deletions()
        token = secrets.token_urlsafe(12)
        recently_deleted[token] = (datetime.now(timezone.utc), columns)
    return jsonify({'message': 'Arbeitsschein erfolgreich gelöscht', 'undo': token})


@app.route('/restore/<token>', methods=['POST'])
def restore_schein(token):
    with schein_lock:
        forget_old_deletions()
        entry = recently_deleted.get(token)
        if not entry:
            return jsonify({'error': 'Rückgängig ist nicht mehr möglich.'}), 410
        columns = dict(entry[1])
        if Arbeitsschein.query.filter_by(ae_nummer=columns['ae_nummer'], vorgang=columns['vorgang']).first():
            return jsonify({'error': 'Diese AE-Nummer mit diesem Vorgang existiert inzwischen wieder.'}), 409
        ae_fach = get_fach_for_ae(columns['ae_nummer'])
        if ae_fach is not None:
            # Andere Vorgänge dieser AE liegen noch da: zurück in deren Mappe.
            columns['fach'] = ae_fach
        elif Arbeitsschein.query.filter_by(fach=columns['fach']).first():
            return jsonify({'error': f"Mappe {columns['fach']} ist inzwischen wieder belegt."}), 409
        schein = Arbeitsschein(**columns)
        db.session.add(schein)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'Diese AE-Nummer mit diesem Vorgang existiert inzwischen wieder.'}), 409
        # Erst nach Erfolg vergessen; bei Fehler bleibt der Schein wiederherstellbar.
        recently_deleted.pop(token, None)
    return jsonify({'message': 'Arbeitsschein wiederhergestellt', 'id': schein.id})

@app.route('/einstellungen', methods=['GET', 'POST'])
def einstellungen():
    state = session_state()
    if state != 'ok':
        return redirect('/login?timeout=1' if state == 'timeout' else '/login')

    import_error = None

    if request.method == 'POST':
        data = request.form

        if 'max_mappen' in data:
            try:
                value = parse_int(data['max_mappen'], 'Maximale Anzahl Mappen', minimum=1, maximum=MAX_MAPPEN_LIMIT)
                upsert_setting('max_mappen', str(value))
                db.session.commit()
            except ValueError as e:
                import_error = str(e)

        if 'max_vorgaenge' in data:
            try:
                value = parse_int(data['max_vorgaenge'], 'Maximale Vorgänge', minimum=10, maximum=MAX_VORGAENGE_LIMIT)
                upsert_setting('max_vorgaenge', str(value))
                db.session.commit()
            except ValueError as e:
                import_error = str(e)

        # Datei-Import Orte
        if 'orte_file' in request.files:
            file = request.files['orte_file']
            if file and file.filename.lower().endswith('.txt'):
                try:
                    content = file.read().decode('utf-8')
                except UnicodeDecodeError:
                    import_error = "Die Orte-Datei konnte nicht gelesen werden (ungültige Zeichenkodierung, bitte als UTF-8 speichern)."
                else:
                    for line in content.splitlines():
                        name = line.strip()
                        if name and len(name) <= MAX_LEN['ort'] and not Ort.query.filter_by(name=name).first():
                            db.session.add(Ort(name=name))

        # Datei-Import Firmen
        if 'firmen_file' in request.files:
            file = request.files['firmen_file']
            if file and file.filename.lower().endswith('.txt'):
                try:
                    content = file.read().decode('utf-8')
                except UnicodeDecodeError:
                    import_error = "Die Firmen-Datei konnte nicht gelesen werden (ungültige Zeichenkodierung, bitte als UTF-8 speichern)."
                else:
                    for line in content.splitlines():
                        name = line.strip()
                        if name and len(name) <= MAX_LEN['firma'] and not Firma.query.filter_by(name=name).first():
                            db.session.add(Firma(name=name))

        db.session.commit()

    orte = Ort.query.order_by(func.lower(Ort.name).asc()).all()
    firmen = Firma.query.order_by(func.lower(Firma.name).asc()).all()

    return render_template('einstellungen.html',
                           max_mappen=get_max_mappen(),
                           max_vorgaenge=get_max_vorgaenge(),
                           orte=orte,
                           firmen=firmen,
                           error=import_error)

@app.route('/ort', methods=['POST'])
def add_ort():
    guard = require_login()
    if guard:
        return guard
    name = (request.get_json(silent=True) or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name darf nicht leer sein'}), 400
    if len(name) > 100:
        return jsonify({'error': 'Name darf höchstens 100 Zeichen lang sein'}), 400
    existing = Ort.query.filter_by(name=name).first()
    if existing:
        return jsonify({'id': existing.id, 'name': existing.name})
    ort = Ort(name=name)
    db.session.add(ort)
    db.session.commit()
    return jsonify({'id': ort.id, 'name': ort.name})

@app.route('/ort/<int:id>', methods=['PUT'])
def update_ort(id):
    guard = require_login()
    if guard:
        return guard
    ort = Ort.query.get_or_404(id)
    name = (request.get_json(silent=True) or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name darf nicht leer sein'}), 400
    if len(name) > 100:
        return jsonify({'error': 'Name darf höchstens 100 Zeichen lang sein'}), 400
    if Ort.query.filter(Ort.name == name, Ort.id != id).first():
        return jsonify({'error': 'Ort existiert bereits'}), 400
    ort.name = name
    db.session.commit()
    return jsonify({'message': 'Ort aktualisiert'})

@app.route('/ort/<int:id>', methods=['DELETE'])
def delete_ort(id):
    guard = require_login()
    if guard:
        return guard
    ort = Ort.query.get_or_404(id)
    db.session.delete(ort)
    db.session.commit()
    return jsonify({'message': 'Ort gelöscht'})

@app.route('/firma', methods=['POST'])
def add_firma():
    guard = require_login()
    if guard:
        return guard
    name = (request.get_json(silent=True) or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name darf nicht leer sein'}), 400
    if len(name) > 100:
        return jsonify({'error': 'Name darf höchstens 100 Zeichen lang sein'}), 400
    existing = Firma.query.filter_by(name=name).first()
    if existing:
        return jsonify({'id': existing.id, 'name': existing.name})
    firma = Firma(name=name)
    db.session.add(firma)
    db.session.commit()
    return jsonify({'id': firma.id, 'name': firma.name})

@app.route('/firma/<int:id>', methods=['PUT'])
def update_firma(id):
    guard = require_login()
    if guard:
        return guard
    firma = Firma.query.get_or_404(id)
    name = (request.get_json(silent=True) or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name darf nicht leer sein'}), 400
    if len(name) > 100:
        return jsonify({'error': 'Name darf höchstens 100 Zeichen lang sein'}), 400
    if Firma.query.filter(Firma.name == name, Firma.id != id).first():
        return jsonify({'error': 'Firma existiert bereits'}), 400
    firma.name = name
    db.session.commit()
    return jsonify({'message': 'Firma aktualisiert'})

@app.route('/firma/<int:id>', methods=['DELETE'])
def delete_firma(id):
    guard = require_login()
    if guard:
        return guard
    firma = Firma.query.get_or_404(id)
    db.session.delete(firma)
    db.session.commit()
    return jsonify({'message': 'Firma gelöscht'})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if check_password_hash(ADMIN_PASSWORD_HASH, request.form.get('password', '')):
            session['logged_in'] = True
            session['last_activity'] = datetime.now(timezone.utc).isoformat()
            return redirect('/einstellungen')
        return render_template('login.html', error="Falsches Passwort")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/uebersicht')
def uebersicht():
    return render_template('uebersicht.html', now=datetime.now())

@app.route('/generate_pdf_now', methods=['POST'])
def generate_pdf_now():
    try:
        filename = generate_pdf()
    except Exception:
        app.logger.exception('PDF-Erzeugung fehlgeschlagen')
        return jsonify({'error': 'PDF konnte nicht erzeugt werden'}), 500
    return jsonify({'filename': filename})


def pdf_safe(value):
    text = '-' if value is None or value == '' else str(value)
    return (
        text.encode('latin-1', 'replace').decode('latin-1')
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


# So viele Dateien bleiben immer liegen, auch wenn sie nach der Uhr alt sind.
# Der Kiosk hat kein Netz und damit keine Zeitsynchronisation: springt die Uhr
# (leere BIOS-Batterie, falsch gestellt), darf das nicht alle Backups löschen.
KEEP_NEWEST_FILES = BACKUP_RETENTION_DAYS


def cleanup_old_files(folder, prefix, suffix):
    """Löscht Dateien älter als BACKUP_RETENTION_DAYS, behält aber immer die neuesten."""
    if not folder or not os.path.isdir(folder):
        return
    cutoff = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
    # Dateinamen enthalten Datum/Uhrzeit, also sortiert der Name chronologisch.
    names = sorted(n for n in os.listdir(folder) if n.startswith(prefix) and n.endswith(suffix))
    for name in names[:-KEEP_NEWEST_FILES]:
        path = os.path.join(folder, name)
        try:
            if datetime.fromtimestamp(os.path.getmtime(path)) < cutoff:
                os.remove(path)
        except OSError:
            pass


def cleanup_old_pdfs(folder):
    cleanup_old_files(folder, 'uebersicht_', '.pdf')


PDF_CELL_MAX_CHARS = 600
pdf_lock = threading.Lock()


def generate_pdf():
    # Der Cron-Job läuft in einem eigenen Thread ohne Request-Kontext.
    # Lock: Knopf und 18-Uhr-Job sollen nicht gleichzeitig dieselbe Datei schreiben.
    with pdf_lock, app.app_context():
        scheine = (
            Arbeitsschein.query
            .order_by(Arbeitsschein.ae_nummer, Arbeitsschein.vorgang)
            .all()
        )
        filename = f"uebersicht_{datetime.now().strftime('%Y-%m-%d')}.pdf"
        filepath = os.path.join(app.static_folder, filename)
        # Erst in eine Zwischendatei, dann umbenennen: ein Abbruch hinterlässt
        # kein halbes PDF unter dem richtigen Namen.
        tmp_path = filepath + '.tmp'

        # Querformat, damit neun Spalten auf A4 passen. Hochformat mit den
        # alten Spaltenbreiten war breiter als die Seite und die Erzeugung
        # ist mit LayoutError abgebrochen.
        doc = SimpleDocTemplate(
            tmp_path,
            pagesize=landscape(A4),
            leftMargin=0.8 * cm,
            rightMargin=0.8 * cm,
            topMargin=1.0 * cm,
            bottomMargin=1.0 * cm,
            title='Arbeitsschein-Übersicht',
        )
        header_style = ParagraphStyle(
            'pdf-header',
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=10,
            textColor=colors.white,
            alignment=TA_CENTER,
        )
        cell_style = ParagraphStyle(
            'pdf-cell',
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            alignment=TA_LEFT,
        )
        title_style = ParagraphStyle(
            'pdf-title',
            fontName='Helvetica-Bold',
            fontSize=12,
            leading=14,
            textColor=colors.HexColor('#002d5a'),
            alignment=TA_LEFT,
        )

        headers = ["AE-Nummer", "Vorgang", "Mappe", "Firma", "Ort", "Mitarbeiter", "Telefon", "Status", "Bemerkung"]
        data = [[Paragraph(pdf_safe(h), header_style) for h in headers]]
        for s in scheine:
            status_de = "In Arbeit" if s.status in ['ausgegeben', 'in arbeit'] else "Zurück"
            row = [
                s.ae_nummer,
                str(s.vorgang),
                str(s.fach),
                s.firma or "-",
                s.ort or "-",
                str(s.personen),
                s.telefonnummer or "-",
                status_de,
                s.bemerkung or "-",
            ]
            # Sehr lange Texte kürzen, eine Zeile höher als die Seite bricht das PDF ab.
            row = [v if len(v) <= PDF_CELL_MAX_CHARS else v[:PDF_CELL_MAX_CHARS] + ' …' for v in row]
            data.append([Paragraph(pdf_safe(value), cell_style) for value in row])

        col_widths = [2.6*cm, 1.8*cm, 1.6*cm, 4.4*cm, 3.4*cm, 2.4*cm, 3.2*cm, 2.6*cm, 5.7*cm]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0078DC')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f8fd')]),
        ]))
        title = Paragraph(
            pdf_safe(f"Arbeitsscheine {datetime.now().strftime('%d.%m.%Y %H:%M')} - {len(scheine)} Einträge"),
            title_style,
        )
        try:
            doc.build([title, Spacer(1, 0.4 * cm), table])
            os.replace(tmp_path, filepath)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        cleanup_old_pdfs(app.static_folder)
        copy_pdf_to_backup_dir(filepath)
        return filename


def copy_pdf_to_backup_dir(filepath):
    """Legt das PDF zusätzlich auf die externe SSD. Fehler dort brechen den Export nicht ab."""
    if not BACKUP_DIR:
        return
    if not os.path.isdir(BACKUP_DIR):
        app.logger.warning('PDF nicht auf SSD kopiert: %s nicht erreichbar', BACKUP_DIR)
        return
    try:
        shutil.copy2(filepath, os.path.join(BACKUP_DIR, os.path.basename(filepath)))
        cleanup_old_pdfs(BACKUP_DIR)
    except OSError:
        app.logger.exception('PDF konnte nicht auf die SSD kopiert werden')


def run_scheduled(job):
    try:
        job()
    except Exception:
        app.logger.exception('Geplanter Job %s ist fehlgeschlagen', getattr(job, '__name__', job))

# ===================== BACKUP =====================
def get_db_path():
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    prefix = 'sqlite:///'
    return uri[len(prefix):] if uri.startswith(prefix) else None

def cleanup_old_backups(directory):
    cleanup_old_files(directory, 'scheine_', '.db')


def latest_backup_age_hours():
    """Alter des neuesten lokalen Backups in Stunden, None wenn es keins gibt."""
    db_path = get_db_path()
    if not db_path:
        return None
    backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
    if not os.path.isdir(backup_dir):
        return None
    times = [os.path.getmtime(os.path.join(backup_dir, n)) for n in os.listdir(backup_dir)
             if n.startswith('scheine_') and n.endswith('.db')]
    if not times:
        return None
    return (datetime.now().timestamp() - max(times)) / 3600


def backup_if_overdue():
    """Beim Start: Backup nachholen, wenn das letzte älter als ein Tag ist (Gerät war um 3 Uhr aus)."""
    with app.app_context():
        age = latest_backup_age_hours()
        if age is None or age > 24:
            backup_database()

def backup_database():
    db_path = get_db_path()
    if not db_path or not os.path.exists(db_path):
        return {'local': None, 'external': False, 'external_error': None}

    backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    filename = f"scheine_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.db"
    local_path = os.path.join(backup_dir, filename)

    source = sqlite3.connect(db_path)
    dest = sqlite3.connect(local_path)
    with dest:
        source.backup(dest)
    source.close()
    dest.close()
    cleanup_old_backups(backup_dir)

    external_ok = False
    external_error = None
    if BACKUP_DIR:
        if os.path.isdir(BACKUP_DIR):
            try:
                shutil.copy2(local_path, os.path.join(BACKUP_DIR, filename))
                cleanup_old_backups(BACKUP_DIR)
                external_ok = True
            except OSError as e:
                external_error = str(e)
        else:
            external_error = f"Backup-Verzeichnis {BACKUP_DIR} nicht erreichbar"

    return {'local': local_path, 'external': external_ok, 'external_error': external_error}

@app.route('/backup_now', methods=['POST'])
def backup_now():
    guard = require_login()
    if guard:
        return guard
    result = backup_database()
    if not result['local']:
        return jsonify({'error': 'Backup fehlgeschlagen: Datenbank nicht gefunden'}), 500
    return jsonify({
        'message': 'Backup erstellt',
        'external': result['external'],
        'external_error': result['external_error']
    })

with app.app_context():
    db.create_all()

# ===================== SCHEDULER =====================
# Startet den Scheduler-Thread beim Import dieses Moduls. Unter Gunicorn deshalb
# nur mit einem einzigen Worker-Prozess betreiben (z.B. --workers 1 --threads 4),
# sonst laufen taeglicher PDF-Export und Backup mehrfach und SQLite bekommt
# gleichzeitige Schreibzugriffe aus mehreren Prozessen.
# AE_SCHEDULER=0 schaltet ihn ab (Tests, flask shell), damit kein zweiter
# Scheduler parallel zur laufenden App Backups oder PDFs schreibt.
# misfire_grace_time: ist der Job zur vollen Stunde verspätet (Neustart, viel
# Last), läuft er innerhalb einer Stunde noch nach statt still auszufallen.
scheduler = BackgroundScheduler(job_defaults={'misfire_grace_time': 3600, 'coalesce': True})
scheduler.add_job(lambda: run_scheduled(generate_pdf), 'cron', hour=18, minute=0, id='daily_pdf')
scheduler.add_job(lambda: run_scheduled(backup_database), 'cron', hour=3, minute=0, id='daily_backup')
if os.environ.get('AE_SCHEDULER', '1') != '0':
    scheduler.add_job(lambda: run_scheduled(backup_if_overdue), 'date',
                      run_date=datetime.now() + timedelta(seconds=60), id='catch_up_backup')
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown() if scheduler.running else None)

# ===================== START =====================
if __name__ == '__main__':
    # Ohne Reloader, sonst importiert Flask das Modul zweimal (zwei Scheduler).
    app.run(debug=True, use_reloader=False)