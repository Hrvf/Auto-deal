"""Orchestration de l'analyse d'une annonce."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..connectors.registry import get_connector
from ..models import Analysis, Listing, utcnow
from . import costs, pricing, reliability, repairs, scoring
from .config import AnalysisConfig, load_config

KEY_FIELDS = ("make", "model", "year", "mileage_km", "price", "fuel", "gearbox", "fiscal_hp", "ct_status", "damages_text")


def vehicle_age(listing: Listing, today: date | None = None) -> int | None:
    today = today or date.today()
    if listing.first_registration:
        try:
            y, m = int(listing.first_registration[:4]), int(listing.first_registration[5:7])
            return max(0, today.year - y - (1 if today.month < m else 0))
        except (ValueError, IndexError):
            pass
    if listing.year:
        return max(0, today.year - listing.year)
    return None


def completeness(listing: Listing) -> float:
    filled = 0
    for f in KEY_FIELDS:
        v = getattr(listing, f)
        if f == "ct_status":
            filled += v != "inconnu"
        else:
            filled += v not in (None, "")
    return filled / len(KEY_FIELDS)


def analyze_listing(db: Session, listing: Listing, cfg: AnalysisConfig | None = None) -> Analysis:
    cfg = cfg or load_config(db)
    try:
        connector = get_connector(listing.platform)
        kind = connector.kind
    except KeyError:
        kind = "annonce"
    age = vehicle_age(listing)
    text = " ".join(x for x in (listing.title, listing.version, listing.engine, listing.model) if x)
    warnings: list[str] = []

    rel_score, alerts = reliability.assess(listing.make, text, listing.year, listing.fuel, listing.mileage_km, age)

    rep_low, rep_high, rep_items = repairs.estimate(
        listing.damages_text, listing.make, listing.is_running, listing.ct_status,
        listing.maintenance_history, kind == "enchere",
    )
    for a in alerts:
        if a.get("expected_cost"):
            rep_items.append({"label": f"Provision risque : {a['title']}", "low": 0, "high": a["expected_cost"],
                              "source": f"probabilité indicative {int(a['probability'] * 100)} %", "is_risk": True})
            rep_high += a["expected_cost"]

    resale = pricing.estimate_resale(db, listing, cfg.general.resale_negotiation_pct)
    if resale.confidence == "aucune":
        warnings.append("Aucune annonce comparable ni cote : importez des annonces Leboncoin/La Centrale du même modèle "
                        "ou saisissez une cote pour estimer la revente.")
    elif resale.confidence == "faible":
        warnings.append("Estimation de revente fragile (moins de 3 comparables).")

    cost = None
    bid = None
    if listing.price:
        cost = costs.compute(
            cfg, platform=listing.platform, kind=kind, price=listing.price,
            includes_fees=listing.price_includes_fees, fiscal_hp=listing.fiscal_hp, age=age,
            ct_status=listing.ct_status, repairs_low=rep_low, repairs_high=rep_high, resale=resale.value,
        )
        if kind == "enchere":
            bid = costs.max_bid(cfg, platform=listing.platform, kind=kind, fiscal_hp=listing.fiscal_hp, age=age,
                                ct_status=listing.ct_status, repairs_low=rep_low, repairs_high=rep_high,
                                resale=resale.value)
        if listing.price_type in ("enchere_depart", "estimation"):
            warnings.append("Prix de départ : le prix final sera plus élevé. Comparez avec l'enchère maximale conseillée.")
    else:
        warnings.append("Prix manquant : la marge ne peut pas être calculée.")
    if listing.mileage_km is None:
        warnings.append("Kilométrage manquant.")
    if not listing.fiscal_hp:
        warnings.append(f"Puissance fiscale inconnue : carte grise calculée sur {cfg.general.default_fiscal_hp} CV.")

    total, breakdown = scoring.score(
        margin_pct=cost.margin_pct if cost else None, reliability=rel_score, price=listing.price,
        repairs_low=rep_low, repairs_high=rep_high, is_running=listing.is_running,
        ct_status=listing.ct_status, mileage_km=listing.mileage_km, age=age, fuel=listing.fuel,
        completeness=completeness(listing),
    )

    analysis = listing.analysis or Analysis(listing=listing)
    analysis.computed_at = utcnow()
    analysis.score = total
    analysis.score_breakdown = breakdown
    analysis.resale_estimate = resale.value
    analysis.resale_low = resale.low
    analysis.resale_high = resale.high
    analysis.resale_confidence = resale.confidence
    analysis.resale_method = resale.method[:200]
    analysis.comparables = resale.comparables[:15]
    analysis.purchase_fees = cost.purchase_fees if cost else 0
    analysis.costs_breakdown = cost.items if cost else []
    analysis.repairs_low = rep_low
    analysis.repairs_high = rep_high
    analysis.repairs_items = rep_items
    analysis.reliability_score = rel_score
    analysis.reliability_alerts = alerts
    analysis.total_cost = cost.total_cost if cost else None
    analysis.margin = cost.margin if cost else None
    analysis.margin_pct = cost.margin_pct if cost else None
    analysis.max_bid = bid
    extra = []
    if cost and cost.vat_on_margin:
        extra.append({"label": "TVA sur marge (régime marchand)", "amount": cost.vat_on_margin})
    if cost and cost.margin_worst is not None:
        extra.append({"label": "Marge si réparations hautes", "amount": cost.margin_worst})
    analysis.warnings = warnings
    analysis.score_breakdown["_extra"] = extra
    db.add(analysis)
    return analysis


def analyze_many(db: Session, listings: Iterable[Listing], cfg: AnalysisConfig | None = None) -> int:
    cfg = cfg or load_config(db)
    n = 0
    for listing in listings:
        analyze_listing(db, listing, cfg)
        n += 1
    db.flush()
    return n


def analyze_related(db: Session, pairs: set[tuple[str, str]]) -> int:
    """Réanalyse toutes les annonces d'un même modèle (les comparables ont changé)."""
    cfg = load_config(db)
    n = 0
    for make, model in pairs:
        if not make or not model:
            continue
        rows = db.scalars(select(Listing).where(
            func.lower(Listing.make) == make.lower(), func.lower(Listing.model) == model.lower()))
        n += analyze_many(db, rows, cfg)
    return n


def analyze_all(db: Session) -> int:
    return analyze_many(db, db.scalars(select(Listing)), load_config(db))
