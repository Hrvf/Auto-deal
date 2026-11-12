import re

from sqlalchemy import select

from app.models import ApiToken, Listing

from .conftest import fixture_bytes

EXT = "chrome-extension://" + "a" * 32


def _token(client) -> str:
    page = client.post("/parametres/jetons", data={"csrf_token": client.csrf, "name": "Test"}).text
    m = re.search(r'id="new-token" readonly value="(adc_[^"]+)"', page)
    assert m, "le jeton doit être affiché une fois"
    return m.group(1)


def _visible_text(html: str) -> str:
    return re.sub(r"<[^>]+>", "\n", html)


def test_token_lifecycle_and_whoami(client, session):
    token = _token(client)
    row = session.scalar(select(ApiToken))
    assert row.token_hash != token and token.startswith(row.prefix)  # jamais stocké en clair
    assert token not in client.get("/parametres").text  # plus jamais réaffiché
    r = client.get("/api/moi", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["email"] == "admin@exemple.fr"
    assert client.get("/api/moi", headers={"Authorization": "Bearer adc_faux"}).status_code == 401
    client.post(f"/parametres/jetons/{row.id}/supprimer", data={"csrf_token": client.csrf})
    assert client.get("/api/moi", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_capture_requires_token_not_cookie(client):
    # Session connectée mais sans jeton : refus (protège contre un site tiers qui ferait poster le navigateur)
    r = client.post("/api/capture", json={"url": "https://www.leboncoin.fr/ad/voitures/1", "html": "<html></html>"})
    assert r.status_code == 401


def test_capture_leboncoin_structured_page(client, session):
    token = _token(client)
    html = fixture_bytes("page_next_data.html").decode()
    r = client.post("/api/capture", headers={"Authorization": f"Bearer {token}"}, json={
        "url": "https://www.leboncoin.fr/ad/voitures/990001", "html": html, "text": _visible_text(html),
        "title": "Peugeot 308"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["plateforme"] == "Leboncoin" and d["prix"] == 11490 and d["kilometrage"] == 95000
    assert d["nouveau"] is True and 0 <= d["note"] <= 100 and d["lien"].endswith(f"/annonces/{d['id']}")
    assert any("PureTech" in a for a in d["alertes"])
    # Recapturer la même page met à jour au lieu de dupliquer
    r2 = client.post("/api/capture", headers={"Authorization": f"Bearer {token}"}, json={
        "url": "https://www.leboncoin.fr/ad/voitures/990001", "html": html})
    assert r2.json()["id"] == d["id"] and r2.json()["nouveau"] is False


def test_capture_page_without_structured_data(client, session):
    token = _token(client)
    html = fixture_bytes("page_lot_sans_donnees.html").decode()
    r = client.post("/api/capture", headers={"Authorization": f"Bearer {token}"}, json={
        "url": "https://www.alcopa-auction.fr/lot/DEMO-778", "html": html, "text": _visible_text(html),
        "title": "RENAULT CLIO IV 1.5 dCi 90 Energy Business (DÉMO)"})
    assert r.status_code == 200, r.text
    lot = session.get(Listing, r.json()["id"])
    assert lot.platform == "alcopa" and lot.price_type == "enchere_depart"
    assert (lot.make, lot.model, lot.price, lot.mileage_km, lot.fiscal_hp) == ("Renault", "Clio", 3900, 134500, 4)
    assert lot.first_registration == "2017-02-14" and lot.fuel == "diesel" and lot.ct_status == "a_refaire"
    labels = {i["label"] for i in lot.analysis.repairs_items}
    assert "Estimation de l'expert de la vente" in labels and "Embrayage" in labels
    assert "Pneumatiques" not in labels  # le menu « Pneus et jantes » n'est pas pris pour un défaut


def test_capture_rejects_unknown_site_without_platform(client):
    token = _token(client)
    r = client.post("/api/capture", headers={"Authorization": f"Bearer {token}"},
                    json={"url": "https://www.exemple.fr/x", "title": "Peugeot 208", "text": "Peugeot 208 5 000 €"})
    assert r.status_code == 422
    r = client.post("/api/capture", headers={"Authorization": f"Bearer {token}"},
                    json={"url": "https://www.exemple.fr/x", "title": "Peugeot 208", "text": "Prix : 5 000 €",
                          "platform": "manuel"})
    assert r.status_code == 200 and r.json()["prix"] == 5000


def test_cors_only_for_extensions(client):
    pre = client.options("/api/capture", headers={"Origin": EXT, "Access-Control-Request-Method": "POST",
                                                  "Access-Control-Request-Headers": "authorization,content-type"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == EXT
    r = client.get("/api/moi", headers={"Origin": "https://site-malveillant.example"})
    assert "access-control-allow-origin" not in r.headers
    r = client.get("/api/annonces", headers={"Origin": EXT})
    assert "access-control-allow-origin" not in r.headers  # les routes à cookie restent fermées


def test_extension_download(client):
    r = client.get("/extension/autodeal-capture.zip")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    import io, json, zipfile
    z = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(z.read("autodeal-capture/manifest.json"))
    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {"activeTab", "scripting", "storage"}
    assert "host_permissions" not in manifest  # aucun accès permanent aux sites


def test_capture_from_iphone_shortcut_text_plain(client):
    """L'app Raccourcis envoie le résultat JavaScript comme un fichier texte, pas en application/json."""
    import json
    token = _token(client)
    html = fixture_bytes("page_lot_sans_donnees.html").decode()
    body = json.dumps({"url": "https://www.alcopa-auction.fr/lot/DEMO-778", "html": html,
                       "text": _visible_text(html), "title": "RENAULT CLIO IV 1.5 dCi 90 Energy Business"})
    r = client.post("/api/capture", content=body.encode(),
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"})
    assert r.status_code == 200, r.text
    resume = r.json()["resume"]
    assert "RENAULT CLIO" in resume and "3 900 €" in resume and "Note provisoire" in resume
    bad = client.post("/api/capture", content=b"pas du json", headers={"Authorization": f"Bearer {token}"})
    assert bad.status_code == 422


def test_settings_shows_iphone_instructions(client):
    page = client.get("/parametres").text
    assert "Exécuter JavaScript sur une page web" in page and "/api/capture" in page


def test_render_style_database_url():
    from app.config import Settings
    s = Settings(database_url="postgres://u:p@h:5432/db", secret_key="x")
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"
