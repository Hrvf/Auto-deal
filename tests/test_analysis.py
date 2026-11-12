from sqlalchemy import select

from app.analysis import costs, reliability, repairs, scoring
from app.analysis.config import AnalysisConfig, GeneralConfig, default_fees
from app.models import Listing
from app.services import import_file

from .conftest import fixture_bytes


def test_reliability_detects_known_issues():
    score, alerts = reliability.assess("Peugeot", "Peugeot 308 1.2 PureTech 130 Allure", 2018, "essence", 98_500, 8)
    assert any(a["id"] == "puretech-courroie" for a in alerts)
    assert score < 75
    score_y, alerts_y = reliability.assess("Toyota", "Yaris 100h Dynamic", 2018, "hybride", 76_000, 8)
    assert any(a["severity"] == "positif" for a in alerts_y)
    assert score_y > score
    # Une Golf diesel 2017 ne doit pas déclencher la règle des TSI essence 2006-2012
    _, golf = reliability.assess("Volkswagen", "Golf 1.6 TDI", 2017, "diesel", 100_000, 9)
    assert not any(a["id"] == "ea111-chaine" for a in golf)


def test_repairs_respect_negations_per_clause():
    low, high, items = repairs.estimate("Pneus neufs, embrayage HS, distribution refaite", "Renault", None, "ok", True, False)
    labels = {i["label"] for i in items}
    assert "Embrayage" in labels
    assert "Pneumatiques" not in labels
    assert not any("Distribution" in l for l in labels)
    assert 600 <= low <= high


def test_repairs_expert_estimate_and_premium():
    low, high, items = repairs.estimate("Rayures. Frais de remise en état estimés : 1 250 €", "BMW", None, "ok", True, True)
    assert items[0]["is_expert"] and low == 1250 and high >= 1250
    l2, h2, _ = repairs.estimate("embrayage", "BMW", None, "ok", True, False)
    l3, h3, _ = repairs.estimate("embrayage", "Dacia", None, "ok", True, False)
    assert l2 > l3


def _cfg(**kw):
    return AnalysisConfig(general=GeneralConfig(**kw), fees=default_fees())


def test_carte_grise_half_price_over_10_years():
    cfg = _cfg(carte_grise_cv_rate=58.0, carte_grise_fixed=13.76)
    assert costs.carte_grise(cfg, 6, 5) == round(6 * 58 + 13.76)
    assert costs.carte_grise(cfg, 6, 12) == round(6 * 58 * 0.5 + 13.76)


def test_costs_margin_and_vat_on_margin():
    cfg = _cfg(vat_regime="marge")
    r = costs.compute(cfg, platform="alcopa", kind="enchere", price=6000, includes_fees=False, fiscal_hp=6, age=8,
                      ct_status="ok", repairs_low=400, repairs_high=800, resale=11000)
    assert r.purchase_fees == int(6000 * 0.14)
    assert r.vat_on_margin == round((11000 - 6000) * 0.2 / 1.2)
    assert r.margin == 11000 - r.total_cost - r.vat_on_margin
    assert r.margin_worst < r.margin


def test_max_bid_reaches_target_margin():
    cfg = _cfg(target_margin_pct=0.15)
    kw = dict(platform="vpauto", kind="enchere", fiscal_hp=5, age=7, ct_status="ok", repairs_low=300, repairs_high=900)
    bid = costs.max_bid(cfg, resale=12000, **kw)
    at_bid = costs.compute(cfg, price=bid, includes_fees=False, resale=12000, **kw)
    above = costs.compute(cfg, price=bid + 200, includes_fees=False, resale=12000, **kw)
    assert at_bid.margin_pct >= 0.15 > above.margin_pct


def test_score_is_bounded_and_explained():
    total, parts = scoring.score(margin_pct=0.5, reliability=100, price=5000, repairs_low=0, repairs_high=0,
                                 is_running=True, ct_status="ok", mileage_km=50000, age=5, fuel="essence", completeness=1)
    assert total == 100
    total, parts = scoring.score(margin_pct=None, reliability=0, price=5000, repairs_low=5000, repairs_high=9000,
                                 is_running=False, ct_status="contre_visite", mileage_km=None, age=25, fuel=None, completeness=0)
    assert 0 <= total <= 10
    assert parts["rentabilite"]["points"] == 0


def test_end_to_end_import_and_analysis(session):
    import_file(session, "leboncoin", "comparables.csv", fixture_bytes("leboncoin_comparables.csv"))
    job = import_file(session, "alcopa", "lots.csv", fixture_bytes("alcopa_lots.csv"))
    assert job.created_count == 6 and job.status == "ok"

    lot = session.scalar(select(Listing).where(Listing.external_id == "DEMO-A1001"))
    a = lot.analysis
    assert a.resale_estimate and a.resale_confidence in {"bonne", "moyenne"}
    assert a.comparables and all(c["platform"] == "leboncoin" for c in a.comparables)
    assert a.margin is not None and a.total_cost > lot.price
    assert a.max_bid and a.max_bid > 0
    assert any(al["id"] == "puretech-courroie" for al in a.reliability_alerts)
    assert 0 <= a.score <= 100

    # Le Clio non roulant en contre-visite doit être moins bien noté que la Yaris
    clio = session.scalar(select(Listing).where(Listing.external_id == "DEMO-A1003")).analysis
    yaris = session.scalar(select(Listing).where(Listing.external_id == "DEMO-A1004")).analysis
    assert yaris.score > clio.score

    # Réimport : mise à jour sans doublon, champs utilisateur préservés
    lot.notes = "à voir sur place"
    lot.favorite = True
    session.commit()
    job2 = import_file(session, "alcopa", "lots.csv", fixture_bytes("alcopa_lots.csv"))
    assert job2.created_count == 0 and job2.updated_count == 6
    session.refresh(lot)
    assert lot.notes == "à voir sur place" and lot.favorite


def test_manual_market_price_overrides(session):
    import_file(session, "alcopa", "lots.csv", fixture_bytes("alcopa_lots.csv"))
    lot = session.scalar(select(Listing).where(Listing.external_id == "DEMO-A1006"))
    assert lot.analysis.resale_estimate is None  # aucun comparable importé
    lot.market_price_manual = 9000
    from app.analysis.engine import analyze_listing
    analyze_listing(session, lot)
    session.commit()
    assert lot.analysis.resale_confidence == "saisie"
    assert lot.analysis.resale_estimate == int(9000 * 0.95)
