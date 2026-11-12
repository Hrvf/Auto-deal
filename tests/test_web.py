import httpx
from sqlalchemy import select

from app.models import ConnectorConfig, Listing, User
from app.security import hash_password
from app.services import FeedError, sync_feed

from .conftest import csrf, fixture_bytes


def _upload(client, platform, name, data, mime="text/csv"):
    return client.post("/imports/fichier", data={"csrf_token": client.csrf, "platform": platform},
                       files={"fichier": (name, data, mime)}, follow_redirects=False)


# --------------------------------------------------------------- Sécurité
def test_private_by_default(anon):
    r = anon.get("/annonces", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/installation") is False
    assert anon.get("/api/annonces").status_code == 401


def test_first_visit_goes_to_setup_then_setup_closes(anon, session):
    assert anon.get("/connexion", follow_redirects=False).headers["location"] == "/installation"
    session.add(User(email="x@y.fr", password_hash=hash_password("motdepasse-solide"), role="admin"))
    session.commit()
    assert anon.get("/installation", follow_redirects=False).headers["location"] == "/connexion"


def test_security_headers(client):
    r = client.get("/")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    cookie = r.headers.get("set-cookie", "") or client.cookies.get("autodeal_session") or ""
    assert cookie


def test_csrf_is_enforced(client):
    r = client.post("/imports/texte", data={"csrf_token": "faux", "platform": "manuel", "texte": "Peugeot 208"})
    assert r.status_code == 400


def test_login_failures_rate_limited(app, session):
    from fastapi.testclient import TestClient
    session.add(User(email="u@exemple.fr", password_hash=hash_password("motdepasse-solide"), role="membre"))
    session.commit()
    with TestClient(app) as c:
        tok = csrf(c.get("/connexion").text)
        for _ in range(5):
            assert c.post("/connexion", data={"csrf_token": tok, "email": "u@exemple.fr", "password": "mauvais"}).status_code == 401
        r = c.post("/connexion", data={"csrf_token": tok, "email": "u@exemple.fr", "password": "motdepasse-solide"})
        assert r.status_code == 429


def test_login_success_and_no_open_redirect(app, session):
    from fastapi.testclient import TestClient
    session.add(User(email="u@exemple.fr", password_hash=hash_password("motdepasse-solide"), role="membre"))
    session.commit()
    with TestClient(app) as c:
        tok = csrf(c.get("/connexion").text)
        r = c.post("/connexion", data={"csrf_token": tok, "email": "U@exemple.fr", "password": "motdepasse-solide",
                                       "suite": "//evil.example.com"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/"
        assert c.get("/annonces").status_code == 200


def test_member_cannot_change_settings(app, session):
    from fastapi.testclient import TestClient
    session.add(User(email="m@exemple.fr", password_hash=hash_password("motdepasse-solide"), role="membre"))
    session.commit()
    with TestClient(app) as c:
        tok = csrf(c.get("/connexion").text)
        c.post("/connexion", data={"csrf_token": tok, "email": "m@exemple.fr", "password": "motdepasse-solide"})
        tok = csrf(c.get("/parametres").text)
        assert c.post("/parametres/analyse", data={"csrf_token": tok}).status_code == 403
        assert c.post("/connecteurs/bca/flux", data={"csrf_token": tok}).status_code == 403


# --------------------------------------------------------------- Parcours
def test_import_list_detail_filters_export(client, session):
    assert _upload(client, "leboncoin", "c.csv", fixture_bytes("leboncoin_comparables.csv")).status_code == 303
    assert _upload(client, "alcopa", "lots.csv", fixture_bytes("alcopa_lots.csv")).status_code == 303
    page = client.get("/imports").text
    assert "Réussi" in page

    r = client.get("/annonces?plateforme=alcopa&tri=marge")
    assert r.status_code == 200 and r.text.count('class="clickable') == 6
    r = client.get("/annonces?plateforme=alcopa&energie=hybride")
    assert "Yaris" in r.text and "Golf" not in r.text
    r = client.get("/annonces?km_max=60000&plateforme=alcopa")
    assert "Sandero" in r.text and "Clio" not in r.text

    lot = session.scalar(select(Listing).where(Listing.external_id == "DEMO-A1001"))
    detail = client.get(f"/annonces/{lot.id}").text
    for expected in ("Détail de la note", "Coût de revient", "PureTech", "Annonces comparables", "Enchère maximale"):
        assert expected in detail

    export = client.get("/annonces/export.csv?plateforme=alcopa")
    assert export.status_code == 200 and "DEMO-A1001" in export.text

    api = client.get(f"/api/annonces/{lot.id}").json()
    assert api["analyse"]["note"] == lot.analysis.score
    assert client.get("/").status_code == 200


def test_html_and_text_import_redirect_to_listing(client):
    r = _upload(client, "leboncoin", "annonce.html", fixture_bytes("page_next_data.html"), "text/html")
    assert r.status_code == 303 and r.headers["location"].startswith("/annonces/")
    r = client.post("/imports/texte", data={"csrf_token": client.csrf, "platform": "domaine",
                                            "texte": "Citroën C3 1.2 PureTech 82\n2017 · 88 000 km · 3 200 €"},
                    follow_redirects=False)
    assert r.headers["location"].startswith("/annonces/")
    detail = client.get(r.headers["location"]).text
    assert "C3" in detail


def test_upload_size_limit(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    r = _upload(client, "alcopa", "lots.csv", fixture_bytes("alcopa_lots.csv"))
    assert r.status_code == 303
    assert "trop volumineux" in client.get("/imports").text


def test_manual_add_edit_track_delete(client, session):
    r = client.post("/annonces/nouvelle", data={
        "csrf_token": client.csrf, "platform": "vpauto", "make": "Peugeot", "model": "208",
        "version": "1.2 PureTech 82 Active", "fuel": "essence", "gearbox": "manuelle", "year": "2019",
        "mileage_km": "61 000", "price": "6 500", "price_type": "enchere_depart", "ct_status": "ok",
        "damages_text": "Rayures pare-chocs", "market_price_manual": "10 500",
    }, follow_redirects=False)
    assert r.status_code == 303
    lid = int(r.headers["location"].rsplit("/", 1)[1])
    listing = session.get(Listing, lid)
    assert listing.analysis.resale_confidence == "saisie" and listing.analysis.margin is not None

    r = client.post(f"/annonces/{lid}/modifier", data={
        "csrf_token": client.csrf, "make": "Peugeot", "model": "208", "version": "1.2 PureTech 82 Active",
        "fuel": "essence", "year": "2019", "mileage_km": "61000", "price": "7000", "price_type": "enchere_depart",
        "ct_status": "ok", "market_price_manual": "10500", "fiscal_hp": "4",
    }, follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    assert session.get(Listing, lid).price == 7000

    for data in ({"action": "favori"}, {"action": "statut", "status": "suivi"}, {"action": "notes", "notes": "OK"}):
        client.post(f"/annonces/{lid}/suivi", data={"csrf_token": client.csrf, **data})
    session.expire_all()
    l = session.get(Listing, lid)
    assert l.favorite and l.status == "suivi" and l.notes == "OK"

    client.post("/filtres", data={"csrf_token": client.csrf, "name": "Mes favoris", "query": "favoris=1"})
    assert "Mes favoris" in client.get("/annonces").text

    client.post(f"/annonces/{lid}/supprimer", data={"csrf_token": client.csrf})
    session.expire_all()
    assert session.get(Listing, lid) is None


def test_settings_change_triggers_reanalysis(client, session):
    _upload(client, "leboncoin", "c.csv", fixture_bytes("leboncoin_comparables.csv"))
    _upload(client, "alcopa", "lots.csv", fixture_bytes("alcopa_lots.csv"))
    lot = session.scalar(select(Listing).where(Listing.external_id == "DEMO-A1002"))
    before = lot.analysis.purchase_fees
    tok = csrf(client.get("/parametres").text)
    r = client.post("/parametres/analyse", data={"csrf_token": tok, "fee_pct_alcopa": "20", "fee_fixed_alcopa": "100"},
                    follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    after = session.get(Listing, lot.id).analysis.purchase_fees
    assert after == int(lot.price * 0.20 + 100) and after != before


# --------------------------------------------------------------- Flux autorisé
def test_feed_requires_authorization_note_and_https(client, session):
    r = client.post("/connecteurs/bca/flux", data={"csrf_token": client.csrf, "feed_url": "http://exemple.fr/x.json",
                                                   "feed_enabled": "on", "authorization_note": "contrat"})
    assert session.get(ConnectorConfig, "bca") is None
    client.post("/connecteurs/bca/flux", data={"csrf_token": client.csrf, "feed_url": "https://exemple.fr/x.json",
                                               "feed_enabled": "on", "authorization_note": ""})
    assert session.get(ConnectorConfig, "bca") is None
    client.post("/connecteurs/bca/flux", data={"csrf_token": client.csrf, "feed_url": "https://exemple.fr/x.json",
                                               "feed_format": "json", "feed_enabled": "on",
                                               "authorization_note": "Accès accordé par BCA (démo)",
                                               "auth_header_name": "Authorization", "auth_header_value": "Bearer secret"})
    session.expire_all()
    cfg = session.get(ConnectorConfig, "bca")
    assert cfg.feed_enabled and cfg.auth_header_value == "Bearer secret"
    page = client.get("/connecteurs").text
    assert "Automatique (flux autorisé)" in page
    assert "Bearer secret" not in page  # le secret n'est jamais réaffiché


def test_sync_feed_with_mock_transport(session):
    session.add(ConnectorConfig(platform="bca", feed_url="https://flux.exemple.fr/export.json", feed_format="json",
                                auth_header_name="Authorization", auth_header_value="Bearer t", feed_enabled=True,
                                authorization_note="démo"))
    session.commit()
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=fixture_bytes("flux_bca.json"))

    job = sync_feed(session, "bca", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen["auth"] == "Bearer t"
    assert job.created_count == 2 and job.source == "flux"
    assert session.get(ConnectorConfig, "bca").last_sync_status.startswith("OK")

    def failing(request):
        return httpx.Response(403)
    try:
        sync_feed(session, "bca", client=httpx.Client(transport=httpx.MockTransport(failing)))
        raise AssertionError("aurait dû échouer")
    except FeedError as exc:
        assert "403" in str(exc)


def test_sync_refused_without_configuration(session):
    try:
        sync_feed(session, "leboncoin")
        raise AssertionError("aurait dû échouer")
    except FeedError:
        pass


def test_installable_app(client):
    page = client.get("/").text
    assert 'rel="manifest"' in page and "apple-touch-icon" in page and 'class="tabbar"' in page
    m = client.get("/static/manifest.webmanifest")
    assert m.status_code == 200 and '"display": "standalone"' in m.text
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["service-worker-allowed"] == "/"
    assert "javascript" in sw.headers["content-type"]
    assert "manifest-src 'self'" in client.get("/").headers["content-security-policy"]
    for icon in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        assert client.get(f"/static/{icon}").status_code == 200
