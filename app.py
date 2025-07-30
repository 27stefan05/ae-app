from flask import Flask, request, jsonify, render_template, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_migrate import Migrate
from datetime import datetime
import os
from apscheduler.schedulers.background import BackgroundScheduler
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///scheine.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Modelle (unverändert)
class Arbeitsschein(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ae_nummer = db.Column(db.String(20), nullable=False, unique=True)
    personen = db.Column(db.Integer, default=0)
    firma = db.Column(db.String(100))
    ort = db.Column(db.String(100))
    telefonnummer = db.Column(db.String(20))
    fach = db.Column(db.Integer, default=0)  # Mappe
    beschreibung = db.Column(db.String(200))
    ausgabedatum = db.Column(db.DateTime, default=datetime.utcnow)
    rueckgabedatum = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='ausgegeben')
    bemerkung = db.Column(db.String(500), nullable=True)

class Ort(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)

class Firma(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True)
    value = db.Column(db.String(50))

# DB initialisieren & Default-Settings
with app.app_context():
    db.create_all()
    if not Setting.query.filter_by(key='max_mappen').first():
        db.session.add(Setting(key='max_mappen', value='300'))
        db.session.commit()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scheine', methods=['GET'])
def liste():
    scheine = Arbeitsschein.query.all()
    return jsonify([{
        'id': s.id,
        'ae_nummer': s.ae_nummer,
        'personen': s.personen,
        'firma': s.firma,
        'ort': s.ort,
        'telefonnummer': s.telefonnummer,
        'fach': s.fach,
        'beschreibung': s.beschreibung,
        'ausgabedatum': s.ausgabedatum.isoformat(),
        'rueckgabedatum': s.rueckgabedatum.isoformat() if s.rueckgabedatum else None,
        'status': s.status,
        'bemerkung': s.bemerkung
    } for s in scheine])

@app.route('/eingabe', methods=['GET', 'POST'])
def eingabe():
    if request.method == 'POST':
        data = request.json if request.is_json else request.form
        # Automatische Mappe zuweisen
        max_mappen = int(Setting.query.filter_by(key='max_mappen').first().value)
        used_mappen = [s.fach for s in Arbeitsschein.query.all() if s.fach > 0]
        fach = next((i for i in range(1, max_mappen + 1) if i not in used_mappen), None)
        if not fach:
            return jsonify({'error': 'Keine freie Mappe verfügbar!'}), 400

        # Neue Ort/Firma hinzufügen, falls angegeben
        if data.get('new_ort'):
            new_ort = Ort(name=data['new_ort'])
            db.session.add(new_ort)
            db.session.commit()
            ort = data['new_ort']
        else:
            ort = data['ort']

        if data.get('new_firma'):
            new_firma = Firma(name=data['new_firma'])
            db.session.add(new_firma)
            db.session.commit()
            firma = data['new_firma']
        else:
            firma = data['firma']

        neuer_schein = Arbeitsschein(
            ae_nummer=data['ae_nummer'],
            personen=int(data['personen']),
            firma=firma,
            ort=ort,
            telefonnummer=data['telefonnummer'],
            fach=fach,
            bemerkung=data.get('bemerkung', '')
        )
        db.session.add(neuer_schein)
        db.session.commit()
        return jsonify({'message': 'Schein gespeichert', 'fach': fach}), 200

    ae_nummer = request.args.get('ae_nummer', '')
    orte = [o.name for o in Ort.query.order_by(func.lower(Ort.name).asc()).all()]
    firmen = [f.name for f in Firma.query.order_by(func.lower(Firma.name).asc()).all()]
    return render_template('eingabe.html', ae_nummer=ae_nummer, orte=orte, firmen=firmen)

@app.route('/rueckgabe/<int:id>', methods=['PUT'])
def rueckgabe(id):
    schein = Arbeitsschein.query.get_or_404(id)
    schein.rueckgabedatum = datetime.utcnow()
    schein.status = 'zurueckgegeben'
    db.session.commit()
    return jsonify({'message': 'Schein zurückgegeben'})

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_page(id):
    schein = Arbeitsschein.query.get_or_404(id)
    if request.method == 'POST':
        data = request.json if request.is_json else request.form
        # Update Felder
        schein.ae_nummer = data['ae_nummer']
        schein.personen = int(data['personen'])
        schein.telefonnummer = data['telefonnummer']
        schein.bemerkung = data.get('bemerkung', schein.bemerkung)
        # Neue Ort/Firma
        if data.get('new_ort'):
            new_ort = Ort(name=data['new_ort'])
            db.session.add(new_ort)
            db.session.commit()
            schein.ort = data['new_ort']
        else:
            schein.ort = data['ort']
        if data.get('new_firma'):
            new_firma = Firma(name=data['new_firma'])
            db.session.add(new_firma)
            db.session.commit()
            schein.firma = data['new_firma']
        else:
            schein.firma = data['firma']
        db.session.commit()
        return jsonify({'message': 'Schein bearbeitet'}), 200

    orte = [o.name for o in Ort.query.order_by(func.lower(Ort.name).asc()).all()]
    firmen = [f.name for f in Firma.query.order_by(func.lower(Firma.name).asc()).all()]
    return render_template('edit.html', schein=schein, orte=orte, firmen=firmen)

@app.route('/delete/<int:id>', methods=['DELETE'])
def delete(id):
    schein = Arbeitsschein.query.get_or_404(id)
    db.session.delete(schein)
    db.session.commit()
    return jsonify({'message': 'Schein gelöscht'})

@app.route('/uebersicht')
def uebersicht():
    scheine = Arbeitsschein.query.all()  # Alle Scheine abrufen
    return render_template('uebersicht.html', scheine=scheine)

@app.route('/einstellungen', methods=['GET', 'POST'])
def einstellungen():
    if request.method == 'POST':
        data = request.form
        if 'max_mappen' in data:
            setting = Setting.query.filter_by(key='max_mappen').first()
            setting.value = data['max_mappen']
            db.session.commit()

        # Multiple Orte hinzufügen
        new_orte = data.getlist('new_ort')  # Holt alle 'new_ort'-Felder
        for ort_name in new_orte:
            if ort_name.strip() and not Ort.query.filter_by(name=ort_name.strip()).first():
                db.session.add(Ort(name=ort_name.strip()))
        db.session.commit()

        # Multiple Firmen hinzufügen
        new_firmen = data.getlist('new_firma')  # Holt alle 'new_firma'-Felder
        for firma_name in new_firmen:
            if firma_name.strip() and not Firma.query.filter_by(name=firma_name.strip()).first():
                db.session.add(Firma(name=firma_name.strip()))
        db.session.commit()

        if 'delete_ort' in data:
            ort = Ort.query.get(data['delete_ort'])
            if ort:
                db.session.delete(ort)
                db.session.commit()

        if 'delete_firma' in data:
            firma = Firma.query.get(data['delete_firma'])
            if firma:
                db.session.delete(firma)
                db.session.commit()

    max_mappen = Setting.query.filter_by(key='max_mappen').first().value
    orte = Ort.query.order_by(func.lower(Ort.name).asc()).all()
    firmen = Firma.query.order_by(func.lower(Firma.name).asc()).all()
    return render_template('einstellungen.html', max_mappen=max_mappen, orte=orte, firmen=firmen)

@app.route('/status/<int:id>', methods=['PUT'])
def change_status(id):
    schein = Arbeitsschein.query.get_or_404(id)
    data = request.json
    schein.status = data['status']
    if data['status'] == 'zurueckgegeben':
        schein.rueckgabedatum = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Status geändert'})

@app.route('/download_pdf')
def download_pdf():
    pdf_files = [f for f in os.listdir(app.static_folder) if f.startswith('uebersicht_') and f.endswith('.pdf')]
    if pdf_files:
        latest_pdf = max(pdf_files, key=lambda x: os.path.getctime(os.path.join(app.static_folder, x)))
        return send_from_directory(app.static_folder, latest_pdf, as_attachment=True)
    return "Kein PDF verfügbar", 404

def generate_pdf():
    with app.app_context():  # Kontext explizit erstellen
        # Hole alle Scheine
        scheine = Arbeitsschein.query.all()
        # Erstelle eine Tabelle mit Daten
        data = [['AE Nummer', 'Mappe', 'Firma', 'Ort', 'Status']]
        for s in scheine:
            data.append([s.ae_nummer, str(s.fach), s.firma or 'N/A', s.ort or 'N/A', s.status])

        # Erstelle das PDF
        pdf_path = os.path.join(app.static_folder, f'uebersicht_{datetime.now().strftime("%Y-%m-%d")}.pdf')
        pdf = SimpleDocTemplate(pdf_path, pagesize=letter)
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements = [table]
        pdf.build(elements)
        print(f"PDF erstellt: {pdf_path}")

# Scheduler initialisieren
scheduler = BackgroundScheduler()
scheduler.add_job(func=generate_pdf, trigger="cron", hour=18, minute=0)  # Täglich um 18:00 Uhr
scheduler.start()

# Korrigierter Shutdown des Schedulers
@app.teardown_appcontext
def shutdown_scheduler(exception=None):
    if scheduler.running:
        try:
            scheduler.shutdown(wait=False)  # Wait=False vermeidet Thread-Join-Probleme
        except RuntimeError:
            pass  # Ignoriere Fehler beim Join des aktuellen Threads

if __name__ == '__main__':
    try:
        app.run(debug=True)
    except KeyboardInterrupt:
        shutdown_scheduler()  # Manuelles Beenden mit Strg+C