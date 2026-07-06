from flask import Flask, request, jsonify, render_template, redirect, url_for, send_from_directory, session, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
import os
import atexit
import secrets
import sqlite3
import shutil
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib.units import cm

load_dotenv()

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
def get_next_fach():
    used = {s.fach for s in Arbeitsschein.query.all()}
    max_mappen = 300
    setting = Setting.query.filter_by(key='max_mappen').first()
    if setting:
        max_mappen = int(setting.value)
    for i in range(1, max_mappen + 1):
        if i not in used:
            return i
    return max_mappen + 1

def require_login():
    if 'logged_in' not in session:
        return jsonify({'error': 'Nicht angemeldet'}), 401
    return None

def get_max_vorgaenge():
    setting = Setting.query.filter_by(key='max_vorgaenge').first()
    return int(setting.value) if setting else 200

def get_vorgang_options(max_vorgaenge):
    return list(range(10, max_vorgaenge + 10, 10))

def parse_int(value, field_name, minimum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} muss eine Zahl sein.")
    if minimum is not None and result < minimum:
        raise ValueError(f"{field_name} muss mindestens {minimum} sein.")
    return result

STATUS_VALUES = {'ausgegeben', 'in arbeit', 'zurueckgegeben'}

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
        ae_nummer = (data.get('ae_nummer') or '').strip()
        firma = data.get('firma', '')
        ort = data.get('ort', '')
        telefonnummer = data.get('telefonnummer', '')
        bemerkung = data.get('bemerkung', '')

        def render_error(message):
            max_vorgaenge = get_max_vorgaenge()
            return render_template('eingabe.html', error=message,
                                   max_vorgaenge=max_vorgaenge, vorgang_options=get_vorgang_options(max_vorgaenge),
                                   next_fach=get_next_fach(),
                                   orte=Ort.query.order_by(func.lower(Ort.name).asc()).all(),
                                   firmen=Firma.query.order_by(func.lower(Firma.name).asc()).all())

        if not ae_nummer:
            return render_error("AE-Nummer darf nicht leer sein.")

        try:
            vorgang = parse_int(data.get('vorgang', 10), 'Vorgang', minimum=10)
            personen = parse_int(data.get('personen') or 0, 'Anzahl Mitarbeiter', minimum=0)
            fach = parse_int(data.get('fach') or get_next_fach(), 'Mappe', minimum=1)
        except ValueError as e:
            return render_error(str(e))

        if firma and not Firma.query.filter_by(name=firma).first():
            db.session.add(Firma(name=firma))
        if ort and not Ort.query.filter_by(name=ort).first():
            db.session.add(Ort(name=ort))
        db.session.commit()

        existing = Arbeitsschein.query.filter_by(ae_nummer=ae_nummer, vorgang=vorgang).first()
        if existing:
            return render_error("Diese AE-Nummer mit diesem Vorgang existiert bereits!")

        schein = Arbeitsschein(
            ae_nummer=ae_nummer,
            vorgang=vorgang,
            personen=personen,
            firma=firma,
            ort=ort,
            telefonnummer=telefonnummer,
            fach=fach,
            bemerkung=bemerkung,
            status='ausgegeben'
        )
        db.session.add(schein)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return render_error("Diese AE-Nummer mit diesem Vorgang existiert bereits!")

        return redirect('/')

    max_vorgaenge = get_max_vorgaenge()
    next_fach = get_next_fach()
    orte = Ort.query.order_by(func.lower(Ort.name).asc()).all()
    firmen = Firma.query.order_by(func.lower(Firma.name).asc()).all()
    return render_template('eingabe.html', next_fach=next_fach, orte=orte, firmen=firmen,
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
                                   selected_firma=schein.firma, selected_ort=schein.ort,
                                   selected_vorgang=schein.vorgang, error=message)

        try:
            personen = parse_int(data.get('personen') or 0, 'Anzahl Mitarbeiter', minimum=0)
            vorgang = parse_int(data.get('vorgang', schein.vorgang), 'Vorgang', minimum=10)
        except ValueError as e:
            return render_error(str(e))

        schein.personen = personen
        schein.vorgang = vorgang
        schein.firma = data.get('firma', '')
        schein.ort = data.get('ort', '')
        schein.telefonnummer = data.get('telefonnummer', '')
        schein.bemerkung = data.get('bemerkung', '')

        if schein.firma and not Firma.query.filter_by(name=schein.firma).first():
            db.session.add(Firma(name=schein.firma))
        if schein.ort and not Ort.query.filter_by(name=schein.ort).first():
            db.session.add(Ort(name=schein.ort))

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return render_error("Diese AE-Nummer mit diesem Vorgang existiert bereits!")

        return redirect('/')

    orte = Ort.query.order_by(func.lower(Ort.name).asc()).all()
    firmen = Firma.query.order_by(func.lower(Firma.name).asc()).all()
    max_vorgaenge = get_max_vorgaenge()
    selected_firma = preselect_firma or schein.firma
    selected_ort = preselect_ort or schein.ort
    return render_template('edit.html', schein=schein, orte=orte, firmen=firmen, max_vorgaenge=max_vorgaenge,
                           vorgang_options=get_vorgang_options(max_vorgaenge),
                           selected_firma=selected_firma, selected_ort=selected_ort,
                           selected_vorgang=schein.vorgang)

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

@app.route('/delete/<int:id>', methods=['DELETE'])
def delete_schein(id):
    schein = db.session.get(Arbeitsschein, id)
    if not schein:
        return jsonify({'error': 'Arbeitsschein nicht gefunden'}), 404
    db.session.delete(schein)
    db.session.commit()
    return jsonify({'message': 'Arbeitsschein erfolgreich gelöscht'})

@app.route('/einstellungen', methods=['GET', 'POST'])
def einstellungen():
    if 'logged_in' not in session:
        return redirect('/login')

    # === Auto-Logout nach 15 Minuten ===
    if 'last_activity' in session:
        try:
            last = datetime.fromisoformat(session['last_activity'])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if (now - last).total_seconds() > 900:
                session.clear()
                return redirect('/login?timeout=1')
        except:
            session.clear()
            return redirect('/login')

    session['last_activity'] = datetime.now(timezone.utc).isoformat()

    import_error = None

    if request.method == 'POST':
        data = request.form

        if 'max_mappen' in data:
            try:
                value = parse_int(data['max_mappen'], 'Maximale Anzahl Mappen', minimum=1)
                setting = Setting.query.filter_by(key='max_mappen').first()
                if setting:
                    setting.value = str(value)
                db.session.commit()
            except ValueError as e:
                import_error = str(e)

        if 'max_vorgaenge' in data:
            try:
                value = parse_int(data['max_vorgaenge'], 'Maximale Vorgänge', minimum=10)
                setting = Setting.query.filter_by(key='max_vorgaenge').first()
                if setting:
                    setting.value = str(value)
                db.session.commit()
            except ValueError as e:
                import_error = str(e)

        # Datei-Import Orte
        if 'orte_file' in request.files:
            file = request.files['orte_file']
            if file and file.filename.endswith('.txt'):
                try:
                    content = file.read().decode('utf-8')
                except UnicodeDecodeError:
                    import_error = "Die Orte-Datei konnte nicht gelesen werden (ungültige Zeichenkodierung, bitte als UTF-8 speichern)."
                else:
                    for line in content.splitlines():
                        name = line.strip()
                        if name and not Ort.query.filter_by(name=name).first():
                            db.session.add(Ort(name=name))

        # Datei-Import Firmen
        if 'firmen_file' in request.files:
            file = request.files['firmen_file']
            if file and file.filename.endswith('.txt'):
                try:
                    content = file.read().decode('utf-8')
                except UnicodeDecodeError:
                    import_error = "Die Firmen-Datei konnte nicht gelesen werden (ungültige Zeichenkodierung, bitte als UTF-8 speichern)."
                else:
                    for line in content.splitlines():
                        name = line.strip()
                        if name and not Firma.query.filter_by(name=name).first():
                            db.session.add(Firma(name=name))

        db.session.commit()

    max_mappen = Setting.query.filter_by(key='max_mappen').first()
    if not max_mappen:
        max_mappen = Setting(key='max_mappen', value='300')
        db.session.add(max_mappen)
        db.session.commit()

    max_vorgaenge_setting = Setting.query.filter_by(key='max_vorgaenge').first()
    if not max_vorgaenge_setting:
        max_vorgaenge_setting = Setting(key='max_vorgaenge', value='200')
        db.session.add(max_vorgaenge_setting)
        db.session.commit()

    max_vorgaenge = int(max_vorgaenge_setting.value)

    orte = Ort.query.order_by(func.lower(Ort.name).asc()).all()
    firmen = Firma.query.order_by(func.lower(Firma.name).asc()).all()

    return render_template('einstellungen.html',
                           max_mappen=max_mappen.value,
                           max_vorgaenge=max_vorgaenge,
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
    filename = generate_pdf()
    return jsonify({'filename': filename})

def generate_pdf():
    scheine = Arbeitsschein.query.all()
    filename = f"uebersicht_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    filepath = os.path.join(app.static_folder, filename)

    doc = SimpleDocTemplate(filepath, pagesize=A4)
    elements = []
    data = [["AE-Nummer", "Vorgang", "Mappe", "Firma", "Ort", "Mitarbeiter", "Telefon", "Status", "Bemerkung"]]

    for s in scheine:
        status_de = "In Arbeit" if s.status in ['ausgegeben', 'in arbeit'] else "Zurück"
        data.append([
            s.ae_nummer,
            str(s.vorgang),
            str(s.fach),
            s.firma or "-",
            s.ort or "-",
            str(s.personen),
            s.telefonnummer or "-",
            status_de,
            s.bemerkung or "-"
        ])

    table = Table(data, colWidths=[2.2*cm, 1.5*cm, 1.3*cm, 3*cm, 2.5*cm, 2*cm, 2.5*cm, 2*cm, 4*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0078DC')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(table)
    doc.build(elements)
    return filename

# ===================== BACKUP =====================
def get_db_path():
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    prefix = 'sqlite:///'
    return uri[len(prefix):] if uri.startswith(prefix) else None

def cleanup_old_backups(directory):
    cutoff = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
    for name in os.listdir(directory):
        if name.startswith('scheine_') and name.endswith('.db'):
            path = os.path.join(directory, name)
            try:
                if datetime.fromtimestamp(os.path.getmtime(path)) < cutoff:
                    os.remove(path)
            except OSError:
                pass

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

# ===================== SCHEDULER =====================
scheduler = BackgroundScheduler()
scheduler.add_job(generate_pdf, 'cron', hour=18, minute=0)
scheduler.add_job(backup_database, 'cron', hour=3, minute=0)
scheduler.start()
atexit.register(lambda: scheduler.shutdown() if scheduler.running else None)

# ===================== START =====================
if __name__ == '__main__':
    with app.app_context():
        os.makedirs(app.instance_path, exist_ok=True)
        db.create_all()
    app.run(debug=True)