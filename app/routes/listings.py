"""Tableau de bord, liste, fiche, saisie et actions sur les annonces."""
from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..analysis.engine import analyze_listing, analyze_related
from ..connectors.base import NormalizedListing
from ..connectors.normalize import (
    department_from_postcode,
    normalize_fuel,
    normalize_gearbox,
    normalize_make,
    normalize_model,
    parse_date,
    parse_int,
    parse_km,
    parse_price,
    parse_year,
)
from ..connectors.registry import all_connectors
from ..db import get_db
from ..models import Analysis, ImportJob, Listing, SavedFilter, User
from ..queries import SORTS, ListingFilters, distinct_makes, search
from ..web import csrf_protect, current_user, flash, render

router = APIRouter()

FUELS = ["essence", "diesel", "hybride", "hybride rechargeable", "électrique", "gpl", "e85"]


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    total = db.scalar(select(func.count(Listing.id)).where(Listing.is_active.is_(True))) or 0
    by_platform = dict(db.execute(
        select(Listing.platform, func.count(Listing.id)).where(Listing.is_active.is_(True)).group_by(Listing.platform)
    ).all())
    top = db.scalars(
        select(Listing).join(Analysis).where(Listing.is_active.is_(True), Listing.status != "ecarte",
                                             Analysis.margin > 0)
        .options(selectinload(Listing.analysis)).order_by(Analysis.score.desc()).limit(8)
    ).all()
    stats = db.execute(select(func.avg(Analysis.score),
                              func.avg(Analysis.margin_pct).filter(Analysis.score >= 60, Analysis.margin > 0),
                              func.count(Analysis.id).filter(Analysis.score >= 60, Analysis.margin > 0),
                              func.max(Analysis.margin))
                       .join(Listing).where(Listing.is_active.is_(True), Listing.status != "ecarte")).one()
    no_resale = db.scalar(select(func.count(Analysis.id)).join(Listing)
                          .where(Listing.is_active.is_(True), Analysis.resale_estimate.is_(None))) or 0
    jobs = db.scalars(select(ImportJob).order_by(ImportJob.id.desc()).limit(5)).all()
    upcoming = db.scalars(
        select(Listing).where(Listing.auction_end.is_not(None), Listing.auction_end >= datetime.now(),
                              Listing.status != "ecarte")
        .options(selectinload(Listing.analysis)).order_by(Listing.auction_end).limit(5)
    ).all()
    return render(request, "dashboard.html", {
        "total": total, "by_platform": by_platform, "top": top, "jobs": jobs, "upcoming": upcoming,
        "avg_score": stats[0], "avg_margin_pct": stats[1], "good_deals": stats[2] or 0, "best_margin": stats[3],
        "no_resale": no_resale,
    })


@router.get("/annonces")
def listings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = ListingFilters.from_params(request.query_params)
    rows, total = search(db, f)
    saved = db.scalars(select(SavedFilter).where(SavedFilter.user_id == user.id).order_by(SavedFilter.name)).all()
    pages = max(1, (total + 29) // 30)
    return render(request, "listings.html", {
        "rows": rows, "total": total, "f": f, "sorts": SORTS, "makes": distinct_makes(db),
        "fuels": FUELS, "saved": saved, "pages": pages,
    })


@router.get("/annonces/export.csv")
def export_csv(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = ListingFilters.from_params(request.query_params)
    rows, _ = search(db, f, page_size=10_000)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Plateforme", "Référence", "Titre", "Marque", "Modèle", "Année", "Kilométrage", "Énergie",
                "Prix", "Note /100", "Revente estimée", "Coût de revient", "Marge", "Marge %", "Enchère max", "URL"])
    for l in rows:
        a = l.analysis
        w.writerow([l.platform, l.external_id, l.title, l.make, l.model, l.year, l.mileage_km, l.fuel, l.price,
                    a.score if a else "", a.resale_estimate if a else "", a.total_cost if a else "",
                    a.margin if a else "", f"{a.margin_pct * 100:.1f}" if a and a.margin_pct is not None else "",
                    a.max_bid if a else "", l.url or ""])
    data = "﻿" + buf.getvalue()  # BOM pour Excel
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="autodeal-annonces.csv"'})


@router.post("/filtres", dependencies=[Depends(csrf_protect)])
def save_filter(request: Request, name: str = Form(...), query: str = Form(""),
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    name = name.strip()[:120]
    if not name:
        flash(request, "Donnez un nom au filtre.", "error")
    else:
        db.add(SavedFilter(user_id=user.id, name=name, query=query[:2000].lstrip("?")))
        db.commit()
        flash(request, f"Filtre « {name} » enregistré.", "success")
    return RedirectResponse(f"/annonces?{query.lstrip('?')}", status_code=303)


@router.post("/filtres/{fid}/supprimer", dependencies=[Depends(csrf_protect)])
def delete_filter(fid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sf = db.get(SavedFilter, fid)
    if sf and sf.user_id == user.id:
        db.delete(sf)
        db.commit()
        flash(request, "Filtre supprimé.", "success")
    return RedirectResponse("/annonces", status_code=303)


def _get_listing(db: Session, lid: int) -> Listing:
    listing = db.get(Listing, lid)
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable.")
    return listing


@router.get("/annonces/nouvelle")
def new_listing_page(request: Request, user: User = Depends(current_user)):
    return render(request, "listing_form.html", {"listing": None, "fuels": FUELS, "connectors_list": all_connectors()})


def _apply_form(listing: Listing, form) -> list[str]:
    errors = []
    title = (form.get("title") or "").strip()[:300]
    listing.make = normalize_make(form.get("make"))
    listing.model = normalize_model(form.get("model"))
    listing.version = (form.get("version") or "").strip()[:200] or None
    listing.title = title or " ".join(x for x in (listing.make, listing.model, listing.version) if x)
    listing.fuel = normalize_fuel(form.get("fuel")) if form.get("fuel") else None
    listing.gearbox = normalize_gearbox(form.get("gearbox")) if form.get("gearbox") else None
    listing.first_registration = parse_date(form.get("first_registration"))
    listing.year = parse_year(form.get("year")) or (int(listing.first_registration[:4]) if listing.first_registration else None)
    listing.mileage_km = parse_km(form.get("mileage_km"))
    listing.fiscal_hp = parse_int(form.get("fiscal_hp"))
    listing.power_hp = parse_int(form.get("power_hp"))
    listing.price = parse_price(form.get("price"))
    pt = form.get("price_type") or "prix_fixe"
    listing.price_type = pt if pt in {"prix_fixe", "enchere_depart", "enchere_actuelle", "adjuge", "estimation"} else "prix_fixe"
    listing.price_includes_fees = form.get("price_includes_fees") == "on"
    listing.market_price_manual = parse_price(form.get("market_price_manual"))
    listing.location = (form.get("location") or "").strip()[:120] or None
    dep = (form.get("department") or "").strip()
    listing.department = dep.zfill(2)[:3] if dep else department_from_postcode(listing.location)
    ct = form.get("ct_status") or "inconnu"
    listing.ct_status = ct if ct in {"ok", "a_refaire", "contre_visite", "inconnu"} else "inconnu"
    running = form.get("is_running")
    listing.is_running = True if running == "oui" else (False if running == "non" else None)
    hist = form.get("maintenance_history")
    listing.maintenance_history = True if hist == "oui" else (False if hist == "non" else None)
    listing.damages_text = (form.get("damages_text") or "").strip()[:5000] or None
    url = (form.get("url") or "").strip()
    listing.url = url if url.startswith(("http://", "https://")) else None
    ae = form.get("auction_end")
    try:
        listing.auction_end = datetime.fromisoformat(ae) if ae else None
    except ValueError:
        errors.append("Date de fin d'enchère invalide.")
    if not listing.title:
        errors.append("Indiquez au moins la marque ou un titre.")
    return errors


@router.post("/annonces/nouvelle", dependencies=[Depends(csrf_protect)])
async def new_listing_submit(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    form = await request.form()
    platform = form.get("platform") or "manuel"
    if platform not in {c.key for c in all_connectors()}:
        platform = "manuel"
    listing = Listing(platform=platform, external_id="tmp", seller_type=None)
    errors = _apply_form(listing, form)
    if errors:
        for e in errors:
            flash(request, e, "error")
        return render(request, "listing_form.html", {"listing": listing, "fuels": FUELS,
                                                      "connectors_list": all_connectors()}, status_code=400)
    tmp = NormalizedListing(platform=platform, external_id=(form.get("external_id") or "").strip() or None,
                            url=listing.url, title=listing.title, make=listing.make, model=listing.model,
                            year=listing.year, mileage_km=listing.mileage_km, price=listing.price, location=listing.location)
    listing.external_id = tmp.ensure_id()
    if db.scalar(select(Listing).where(Listing.platform == platform, Listing.external_id == listing.external_id)):
        flash(request, "Cette annonce existe déjà.", "error")
        return render(request, "listing_form.html", {"listing": listing, "fuels": FUELS,
                                                      "connectors_list": all_connectors()}, status_code=400)
    db.add(listing)
    db.flush()
    analyze_related(db, {(listing.make, listing.model)} if listing.make and listing.model else set())
    analyze_listing(db, listing)
    db.commit()
    flash(request, "Véhicule ajouté et analysé.", "success")
    return RedirectResponse(f"/annonces/{listing.id}", status_code=303)


@router.get("/annonces/{lid}")
def listing_detail(lid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    listing = _get_listing(db, lid)
    if not listing.analysis:
        analyze_listing(db, listing)
        db.commit()
    return render(request, "listing_detail.html", {"l": listing, "a": listing.analysis})


@router.get("/annonces/{lid}/modifier")
def edit_listing_page(lid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return render(request, "listing_form.html", {"listing": _get_listing(db, lid), "fuels": FUELS,
                                                  "connectors_list": all_connectors()})


@router.post("/annonces/{lid}/modifier", dependencies=[Depends(csrf_protect)])
async def edit_listing_submit(lid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    listing = _get_listing(db, lid)
    old = (listing.make, listing.model)
    errors = _apply_form(listing, await request.form())
    if errors:
        db.rollback()
        for e in errors:
            flash(request, e, "error")
        return RedirectResponse(f"/annonces/{lid}/modifier", status_code=303)
    db.flush()
    analyze_related(db, {p for p in (old, (listing.make, listing.model)) if p[0] and p[1]})
    analyze_listing(db, listing)
    db.commit()
    flash(request, "Fiche mise à jour et réanalysée.", "success")
    return RedirectResponse(f"/annonces/{lid}", status_code=303)


@router.post("/annonces/{lid}/suivi", dependencies=[Depends(csrf_protect)])
async def listing_tracking(lid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    listing = _get_listing(db, lid)
    form = await request.form()
    action = form.get("action")
    if action == "favori":
        listing.favorite = not listing.favorite
    elif action == "statut" and form.get("status") in {"nouveau", "suivi", "ecarte", "achete"}:
        listing.status = form.get("status")
    elif action == "notes":
        listing.notes = (form.get("notes") or "").strip()[:5000] or None
    elif action == "reanalyser":
        analyze_listing(db, listing)
        flash(request, "Analyse recalculée.", "success")
    db.commit()
    back = form.get("retour") or f"/annonces/{lid}"
    return RedirectResponse(back if back.startswith("/") and not back.startswith("//") else "/", status_code=303)


@router.post("/annonces/{lid}/supprimer", dependencies=[Depends(csrf_protect)])
def delete_listing(lid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    listing = _get_listing(db, lid)
    pair = (listing.make, listing.model)
    db.delete(listing)
    db.flush()
    if pair[0] and pair[1]:
        analyze_related(db, {pair})
    db.commit()
    flash(request, "Annonce supprimée.", "success")
    return RedirectResponse("/annonces", status_code=303)
