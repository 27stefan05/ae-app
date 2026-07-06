import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module


@pytest.fixture()
def client():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    app_module.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app_module.app.config['TESTING'] = True
    with app_module.app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
    with app_module.app.test_client() as test_client:
        yield test_client
    os.close(db_fd)
    os.unlink(db_path)


def login(client):
    return client.post('/login', data={'password': 'test'}, follow_redirects=True)


def create_schein(client, ae_nummer, vorgang='10', **extra):
    payload = {'ae_nummer': ae_nummer, 'vorgang': vorgang, 'personen': '1'}
    payload.update(extra)
    return client.post('/eingabe', data=payload)


def test_index_loads(client):
    assert client.get('/').status_code == 200


def test_create_and_list_schein(client):
    resp = create_schein(client, '12345678', firma='TestFirma', ort='TestOrt', telefonnummer='0123', bemerkung='x')
    assert resp.status_code == 302
    data = client.get('/scheine').get_json()
    assert len(data) == 1
    assert data[0]['ae_nummer'] == '12345678'
    assert data[0]['firma'] == 'TestFirma'


def test_duplicate_ae_nummer_shows_error_not_crash(client):
    create_schein(client, '11112222')
    resp = create_schein(client, '11112222')
    assert resp.status_code == 200
    assert 'existiert bereits' in resp.get_data(as_text=True)
    assert len(client.get('/scheine').get_json()) == 1


def test_eingabe_invalid_vorgang_shows_error_not_crash(client):
    resp = create_schein(client, '99999999', vorgang='abc')
    assert resp.status_code == 200
    assert 'Zahl' in resp.get_data(as_text=True)
    assert client.get('/scheine').get_json() == []


def test_eingabe_empty_ae_nummer_shows_error(client):
    resp = create_schein(client, '')
    assert resp.status_code == 200
    assert 'AE-Nummer' in resp.get_data(as_text=True)


def test_status_change_valid(client):
    create_schein(client, '55556666')
    schein_id = client.get('/scheine').get_json()[0]['id']
    resp = client.put(f'/status/{schein_id}', json={'status': 'zurueckgegeben'})
    assert resp.status_code == 200
    assert client.get('/scheine').get_json()[0]['status'] == 'zurueckgegeben'


def test_status_change_missing_field_returns_400(client):
    create_schein(client, '77778888')
    schein_id = client.get('/scheine').get_json()[0]['id']
    resp = client.put(f'/status/{schein_id}', json={})
    assert resp.status_code == 400


def test_status_change_invalid_value_returns_400(client):
    create_schein(client, '13131414')
    schein_id = client.get('/scheine').get_json()[0]['id']
    resp = client.put(f'/status/{schein_id}', json={'status': 'kaputt'})
    assert resp.status_code == 400


def test_delete_schein(client):
    create_schein(client, '10101010')
    schein_id = client.get('/scheine').get_json()[0]['id']
    resp = client.delete(f'/delete/{schein_id}')
    assert resp.status_code == 200
    assert client.get('/scheine').get_json() == []


def test_delete_missing_schein_returns_404(client):
    assert client.delete('/delete/9999').status_code == 404


def test_edit_updates_fields(client):
    create_schein(client, '30303030')
    schein_id = client.get('/scheine').get_json()[0]['id']
    resp = client.post(f'/edit/{schein_id}', data={'personen': '3', 'vorgang': '10', 'firma': 'NeueFirma'})
    assert resp.status_code == 302
    data = client.get('/scheine').get_json()[0]
    assert data['personen'] == 3
    assert data['firma'] == 'NeueFirma'


def test_edit_invalid_vorgang_shows_error_not_crash(client):
    create_schein(client, '40404040')
    schein_id = client.get('/scheine').get_json()[0]['id']
    resp = client.post(f'/edit/{schein_id}', data={'personen': '1', 'vorgang': 'abc'})
    assert resp.status_code == 200
    assert 'Zahl' in resp.get_data(as_text=True)


def test_eingabe_accepts_non_multiple_of_ten_vorgang(client):
    resp = create_schein(client, '50505050', vorgang='11')
    assert resp.status_code == 302
    assert client.get('/scheine').get_json()[0]['vorgang'] == 11


def test_edit_page_preselects_non_standard_vorgang(client):
    create_schein(client, '60606060', vorgang='11')
    schein_id = client.get('/scheine').get_json()[0]['id']
    body = client.get(f'/edit/{schein_id}').get_data(as_text=True)
    assert 'value="11"' in body


def test_edit_keeps_non_standard_vorgang_when_unchanged(client):
    create_schein(client, '70707070', vorgang='11')
    schein_id = client.get('/scheine').get_json()[0]['id']
    resp = client.post(f'/edit/{schein_id}', data={'personen': '1', 'vorgang': '11'})
    assert resp.status_code == 302
    assert client.get('/scheine').get_json()[0]['vorgang'] == 11


def test_edit_preselect_creates_and_selects_new_firma(client):
    create_schein(client, '20202020')
    schein_id = client.get('/scheine').get_json()[0]['id']

    resp = client.get(f'/edit/{schein_id}?preselect_firma=NeueFirma')
    assert resp.status_code == 200
    assert 'NeueFirma' in resp.get_data(as_text=True)

    login(client)
    assert 'NeueFirma' in client.get('/einstellungen').get_data(as_text=True)


def test_einstellungen_requires_login(client):
    assert client.get('/einstellungen', follow_redirects=False).status_code == 302


def test_login_logout(client):
    assert login(client).status_code == 200
    assert client.get('/einstellungen').status_code == 200
    client.get('/logout')
    assert client.get('/einstellungen', follow_redirects=False).status_code == 302


def test_login_wrong_password(client):
    resp = client.post('/login', data={'password': 'falsch'})
    assert resp.status_code == 200
    assert 'Falsches Passwort' in resp.get_data(as_text=True)


def test_login_with_custom_password_hash(client, monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setattr(app_module, 'ADMIN_PASSWORD_HASH', generate_password_hash('geheim123'))

    resp = client.post('/login', data={'password': 'geheim123'})
    assert resp.status_code == 302

    resp = client.post('/login', data={'password': 'test'})
    assert resp.status_code == 200
    assert 'Falsches Passwort' in resp.get_data(as_text=True)


def test_ort_requires_login(client):
    assert client.post('/ort', json={'name': 'Testort'}).status_code == 401


def test_ort_crud(client):
    login(client)
    resp = client.post('/ort', json={'name': 'Teststadt'})
    assert resp.status_code == 200
    ort_id = resp.get_json()['id']

    assert client.put(f'/ort/{ort_id}', json={'name': 'Teststadt2'}).status_code == 200
    assert client.delete(f'/ort/{ort_id}').status_code == 200


def test_ort_add_empty_name_rejected(client):
    login(client)
    assert client.post('/ort', json={'name': '  '}).status_code == 400


def test_firma_crud(client):
    login(client)
    resp = client.post('/firma', json={'name': 'TestFirma'})
    assert resp.status_code == 200
    firma_id = resp.get_json()['id']

    assert client.put(f'/firma/{firma_id}', json={'name': 'TestFirma2'}).status_code == 200
    assert client.delete(f'/firma/{firma_id}').status_code == 200
