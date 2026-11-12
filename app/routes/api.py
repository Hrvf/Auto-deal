"""API JSON (lecture) : base pour une future application ou un site public."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis.scoring import verdict
from ..connectors.registry import platform_name
from ..db import get_db
from ..models import ApiToken, Listing, User, utcnow
from ..queries import ListingFilters, search
from ..security import hash_api_token
from ..services import CaptureError, capture_page
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


# ---------------------------------------------------------------- Extension
def token_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Authentification par jeton personnel (en-tête Authorization: Bearer adc_...).

    Les cookies ne sont pas acceptés ici : un site tiers ne peut donc pas déclencher de capture."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Jeton manquant.")
    token = auth[7:].strip()
    row = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_api_token(token))) if token else None
    user = db.get(User, row.user_id) if row else None
    if not row or not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Jeton invalide ou révoqué.")
    row.last_used_at = utcnow()
    db.commit()
    return user


@router.get("/moi")
def whoami(user: User = Depends(token_user)):
    return {"email": user.email, "nom": user.display_name or user.email}


class CaptureIn(BaseModel):
    url: str = Field(max_length=2000)
    title: str | None = Field(default=None, max_length=500)
    html: str | None = None
    text: str | None = None
    platform: str | None = Field(default=None, max_length=40)


MAX_CAPTURE_BODY = 8 * 1024 * 1024


@router.post("/capture")
async def capture_endpoint(request: Request, db: Session = Depends(get_db), user: User = Depends(token_user)):
    """Accepte du JSON quel que soit le Content-Type (l'app Raccourcis d'iPhone envoie parfois du text/plain)."""
    body = await request.body()
    if len(body) > MAX_CAPTURE_BODY:
        raise HTTPException(status_code=413, detail="Page trop volumineuse.")
    try:
        payload = CaptureIn.model_validate(json.loads(body.decode("utf-8", errors="replace")))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Données de capture invalides.") from exc
    return capture(payload, request, db, user)


def capture(payload: CaptureIn, request: Request, db: Session, user: User):
    try:
        job, listing = capture_page(db, url=payload.url, html=payload.html, text=payload.text,
                                    title=payload.title, user_id=user.id, platform=payload.platform)
    except CaptureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not listing:
        raise HTTPException(status_code=422, detail="; ".join(job.errors) or "Aucun véhicule reconnu.")
    a = listing.analysis
    base = str(request.base_url).rstrip("/")
    return {
        "resume": _summary(listing, a),
        "id": listing.id,
        "nouveau": job.created_count == 1,
        "plateforme": platform_name(listing.platform),
        "titre": listing.title,
        "prix": listing.price,
        "kilometrage": listing.mileage_km,
        "annee": listing.year,
        "note": a.score if a else None,
        "verdict": verdict(a.score)[0] if a else None,
        "revente": a.resale_estimate if a else None,
        "marge": a.margin if a else None,
        "marge_pct": a.margin_pct if a else None,
        "enchere_max": a.max_bid if a else None,
        "alertes": [x["title"] for x in (a.reliability_alerts if a else []) if x["severity"] in ("eleve", "moyen")],
        "avertissements": (job.errors or []) + ((a.warnings if a else [])[:2]),
        "lien": f"{base}/annonces/{listing.id}",
    }


def _eur(v) -> str:
    return "—" if v is None else f"{int(v):,} €".replace(",", " ")


def _summary(listing: Listing, a) -> str:
    """Texte court affiché par le Raccourci iPhone."""
    lines = [listing.title[:80]]
    if not a:
        return lines[0]
    if a.resale_estimate is None:
        lines.append(f"Note provisoire {a.score}/100 (revente inconnue)")
    else:
        lines.append(f"Note {a.score}/100 · {verdict(a.score)[0]}")
    lines.append(f"Prix {_eur(listing.price)} · Revente {_eur(a.resale_estimate)}")
    if a.margin is not None:
        pct = f" ({a.margin_pct * 100:.1f} %)".replace(".", ",") if a.margin_pct is not None else ""
        lines.append(f"Marge nette {_eur(a.margin)}{pct}")
    if a.max_bid is not None:
        lines.append(f"Enchère max conseillée {_eur(a.max_bid)}")
    risks = [x["title"] for x in a.reliability_alerts if x["severity"] == "eleve"]
    if risks:
        lines.append("⚠ " + risks[0])
    return "\n".join(lines)
