"""API JSON (lecture) : base pour une future application ou un site public."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Listing, User
from ..queries import ListingFilters, search
from ..web import current_user

router = APIRouter(prefix="/api")


def serialize(l: Listing, full: bool = False) -> dict:
    a = l.analysis
    data = {
        "id": l.id, "plateforme": l.platform, "reference": l.external_id, "url": l.url, "titre": l.title,
        "marque": l.make, "modele": l.model, "version": l.version, "annee": l.year, "kilometrage": l.mileage_km,
        "energie": l.fuel, "boite": l.gearbox, "prix": l.price, "type_prix": l.price_type,
        "departement": l.department, "statut": l.status, "favori": l.favorite,
        "analyse": None if not a else {
            "note": a.score, "revente_estimee": a.resale_estimate, "confiance_revente": a.resale_confidence,
            "cout_de_revient": a.total_cost, "marge": a.margin, "marge_pct": a.margin_pct,
            "enchere_max": a.max_bid, "reparations": [a.repairs_low, a.repairs_high],
            "fiabilite": a.reliability_score,
        },
    }
    if full and a:
        data["analyse"].update({
            "detail_note": {k: v for k, v in a.score_breakdown.items() if not k.startswith("_")},
            "couts": a.costs_breakdown, "postes_reparation": a.repairs_items,
            "alertes_fiabilite": a.reliability_alerts, "comparables": a.comparables, "avertissements": a.warnings,
        })
    return data


@router.get("/annonces")
def api_listings(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = ListingFilters.from_params(request.query_params)
    rows, total = search(db, f)
    return {"total": total, "page": f.page, "resultats": [serialize(r) for r in rows]}


@router.get("/annonces/{lid}")
def api_listing(lid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    listing = db.get(Listing, lid)
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable.")
    return serialize(listing, full=True)
