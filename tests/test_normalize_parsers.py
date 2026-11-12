from app.connectors.normalize import (
    department_from_postcode,
    normalize_ct,
    normalize_fuel,
    normalize_gearbox,
    parse_date,
    parse_km,
    parse_price,
    split_title,
)
from app.connectors.registry import all_connectors, get_connector

from .conftest import fixture_bytes


def test_parse_numbers():
    assert parse_price("12 500 €") == 12500
    assert parse_price("12.500") == 12500
    assert parse_price("9 990,00 €") == 9990
    assert parse_price("0") is None
    assert parse_km("125 000 km") == 125000
    assert parse_km("abc") is None


def test_parse_dates():
    assert parse_date("15/03/2018") == "2018-03-15"
    assert parse_date("03/2014") == "2014-03-01"
    assert parse_date("2019-04-12T00:00:00") == "2019-04-12"
    assert parse_date("n'importe quoi") is None


def test_vocabulary():
    assert normalize_fuel("Gazole") == "diesel"
    assert normalize_fuel("1.6 BlueHDi 120") == "diesel"
    assert normalize_fuel("Hybride rechargeable") == "hybride rechargeable"
    assert normalize_fuel("ES") == "essence"
    assert normalize_gearbox("BVA") == "automatique"
    assert normalize_gearbox("DSG7") == "automatique"
    assert normalize_gearbox("Mécanique") == "manuelle"
    assert normalize_ct("À refaire") == "a_refaire"
    assert normalize_ct("Contre-visite") == "contre_visite"
    assert normalize_ct("Favorable") == "ok"
    assert split_title("VW Golf VII 1.6 TDI") == ("Volkswagen", "Golf")
    assert split_title("Land Rover Range Rover Evoque")[0] == "Land Rover"
    assert department_from_postcode("33700 Mérignac") == "33"
    assert department_from_postcode("20000") == "2A"


def test_every_platform_has_independent_connector():
    keys = {c.key for c in all_connectors()}
    assert {"alcopa", "vpauto", "domaine", "bca", "leboncoin", "lacentrale"} <= keys
    for c in all_connectors():
        assert c.status_reason, f"{c.key} doit expliquer son statut"
        assert c.how_to_export


def test_no_connector_claims_automatic_scraping():
    for c in all_connectors():
        assert c.status.value != "auto"
        try:
            c.auto_fetch()
            raise AssertionError("auto_fetch aurait dû être refusé")
        except Exception as exc:  # ConnectorNotAuthorized
            assert exc.__class__.__name__ == "ConnectorNotAuthorized"


def test_csv_cp1252_auction_lots():
    res = get_connector("alcopa").parse_file("lots.csv", fixture_bytes("alcopa_lots.csv"))
    assert not res.errors
    assert len(res.listings) == 6
    lot = res.listings[0]
    assert (lot.make, lot.model, lot.year, lot.mileage_km, lot.price) == ("Peugeot", "308", 2018, 98500, 6900)
    assert lot.price_type == "enchere_depart"
    assert lot.ct_status == "a_refaire"
    assert lot.department == "33"
    assert lot.external_id == "DEMO-A1001"
    clio = res.listings[2]
    assert clio.is_running is False and clio.ct_status == "contre_visite" and clio.gearbox == "automatique"


def test_csv_unknown_columns_reports_error():
    res = get_connector("leboncoin").parse_file("x.csv", "foo;bar\n1;2\n".encode())
    assert res.listings == []
    assert "Aucune colonne reconnue" in res.errors[0]


def test_json_feed():
    res = get_connector("bca").parse_file("flux.json", fixture_bytes("flux_bca.json"))
    assert len(res.listings) == 2
    golf = res.listings[0]
    assert golf.external_id == "DEMO-BCA-1"
    assert golf.department == "33" and golf.location == "Lormont"
    assert golf.year == 2016 and golf.damages_text.startswith("Rayures")


def test_html_next_data_page():
    res = get_connector("leboncoin").parse_file("annonce.html", fixture_bytes("page_next_data.html"))
    assert len(res.listings) == 1
    ad = res.listings[0]
    assert ad.external_id == "990001"
    assert (ad.make, ad.model, ad.year, ad.mileage_km, ad.price) == ("Peugeot", "308", 2018, 95000, 11490)
    assert ad.fuel == "essence" and ad.gearbox == "manuelle" and ad.fiscal_hp == 6
    assert ad.department == "33"
    assert "alert" not in (ad.damages_text or "")  # le contenu des scripts n'est jamais repris


def test_html_jsonld_page():
    res = get_connector("lacentrale").parse_file("annonce.htm", fixture_bytes("page_jsonld.html"))
    car = res.listings[0]
    assert car.external_id == "DEMO-LC-777"
    assert (car.make, car.model, car.price, car.mileage_km) == ("Toyota", "Yaris", 14290, 61000)
    assert car.first_registration == "2019-04-12" and car.fuel == "hybride"


def test_free_text():
    txt = "Renault Clio IV 1.2 TCe 120 EDC\nMise en circulation : 03/2014\n112 000 km\nPrix : 4 500 €\nNon roulant"
    res = get_connector("vpauto").parse_text(txt)
    l = res.listings[0]
    assert (l.make, l.model, l.year, l.mileage_km, l.price) == ("Renault", "Clio", 2014, 112000, 4500)
    assert l.is_running is False and l.gearbox == "automatique"
