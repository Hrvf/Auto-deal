"""Estimation du prix de revente à partir d'annonces comparables de la base."""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..connectors.registry import all_connectors
from ..models import Listing

YEAR_ADJ = 0.07        # écart de valeur par année d'âge
KM_ADJ_PER_10K = 0.015 # écart de valeur par tranche de 10 000 km


@dataclass
class ResaleEstimate:
    value: int | None = None
    low: int | None = None
    high: int | None = None
    confidence: str = "aucune"   # bonne | moyenne | faible | saisie | aucune
    method: str = "Pas assez de données"
    comparables: list[dict] = field(default_factory=list)


def retail_platforms() -> list[str]:
    return [c.key for c in all_connectors() if c.is_retail_reference] + ["manuel"]


def _percentile(values: list[float], q: float) -> float:
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def find_comparables(db: Session, listing: Listing, limit: int = 40, widened: bool = False) -> list[Listing]:
    """Annonces du même modèle. `widened` élargit l'âge (±3 ans) et le kilométrage (±60 %)."""
    if not listing.make or not listing.model:
        return []
    years = 3 if widened else 2
    q = select(Listing).where(
        Listing.id != (listing.id or -1),
        Listing.is_active.is_(True),
        func.lower(Listing.make) == listing.make.lower(),
        func.lower(Listing.model) == listing.model.lower(),
        Listing.price.is_not(None),
        Listing.price_type == "prix_fixe",
        Listing.platform.in_(retail_platforms()),
    )
    if listing.year:
        q = q.where(Listing.year.between(listing.year - years, listing.year + years))
    if listing.fuel:
        q = q.where((Listing.fuel == listing.fuel) | Listing.fuel.is_(None))
    candidates = list(db.scalars(q.limit(500)))
    if listing.mileage_km:
        band = max(50_000, int(listing.mileage_km * 0.6)) if widened else max(30_000, int(listing.mileage_km * 0.4))
        candidates = [c for c in candidates if c.mileage_km is None or abs(c.mileage_km - listing.mileage_km) <= band]
        candidates.sort(key=lambda c: abs((c.mileage_km or listing.mileage_km) - listing.mileage_km))
    return candidates[:limit]


def adjust_price(comp: Listing, target: Listing) -> float:
    factor = 1.0
    if comp.year and target.year:
        factor *= 1 + YEAR_ADJ * (target.year - comp.year)
    if comp.mileage_km is not None and target.mileage_km is not None:
        factor *= 1 - KM_ADJ_PER_10K * (target.mileage_km - comp.mileage_km) / 10_000
    factor = max(0.6, min(1.4, factor))
    return comp.price * factor


def estimate_resale(db: Session, listing: Listing, negotiation_pct: float) -> ResaleEstimate:
    comps = find_comparables(db, listing)
    widened = False
    if len(comps) < 3:
        wider = find_comparables(db, listing, widened=True)
        if len(wider) > len(comps):
            comps, widened = wider, True
    est = ResaleEstimate()
    if comps:
        adjusted = [adjust_price(c, listing) for c in comps]
        net = 1 - negotiation_pct
        est.value = int(round(median(adjusted) * net, -1))
        est.low = int(round(_percentile(adjusted, 0.25) * net, -1))
        est.high = int(round(_percentile(adjusted, 0.75) * net, -1))
        n = len(comps)
        est.confidence = "faible" if widened else ("bonne" if n >= 8 else ("moyenne" if n >= 3 else "faible"))
        crit = "±3 ans, kilométrage ±60 % — critères élargis" if widened else "±2 ans, kilométrage proche"
        est.method = (f"Médiane de {n} annonce{'s' if n > 1 else ''} comparable{'s' if n > 1 else ''} "
                      f"(même modèle, {crit}), ajustée âge/km, "
                      f"moins {int(negotiation_pct * 100)} % de négociation")
        est.comparables = [
            {"id": c.id, "title": c.title, "platform": c.platform, "year": c.year,
             "mileage_km": c.mileage_km, "price": c.price, "adjusted": int(round(a, -1))}
            for c, a in zip(comps, adjusted)
        ]
    if listing.market_price_manual:
        manual = int(listing.market_price_manual * (1 - negotiation_pct))
        est.method = (f"Cote saisie ({listing.market_price_manual:,} €) moins {int(negotiation_pct * 100)} % de négociation"
                      .replace(",", " ")) + (f" — {len(comps)} comparable(s) affichés pour contrôle" if comps else "")
        est.value = manual
        est.low = int(manual * 0.92) if not comps else min(est.low or manual, manual)
        est.high = int(manual * 1.05) if not comps else max(est.high or manual, manual)
        est.confidence = "saisie"
    return est
