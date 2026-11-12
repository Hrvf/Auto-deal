"""Imports manuels et pilotage des connecteurs."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..connectors.base import ConnectorStatus
from ..connectors.registry import all_connectors, get_connector
from ..db import get_db
from ..models import ConnectorConfig, ImportJob, Listing, User
from ..services import FeedError, import_file, import_text, sync_feed, validate_feed_url
from ..web import admin_user, csrf_protect, current_user, flash, render

router = APIRouter()

CSV_TEMPLATE = (
    "reference;url;marque;modele;version;energie;boite;date de mise en circulation;kilometrage;"
    "puissance fiscale;prix;type de prix;ville;code postal;controle technique;roulant;dommages;date de vente;cote\n"
    "A1234;https://exemple.fr/lot/A1234;Peugeot;308;1.2 PureTech 130 Allure;Essence;Manuelle;15/03/2018;98500;"
    "6;7900;enchere_depart;Mérignac;33700;À refaire;oui;Pare-brise fissuré, rayures porte AR;2026-11-20 14:00;\n"
)


def _valid_platform(key: str) -> str:
    try:
        return get_connector(key).key
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Plateforme inconnue.") from exc


def effective_status(connector, cfg: ConnectorConfig | None) -> tuple[str, str]:
    if cfg and cfg.feed_enabled and cfg.feed_url:
        return "auto", "Automatique (flux autorisé)"
    return connector.status.value, connector.status.label


@router.get("/imports")
def imports_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    jobs = db.scalars(select(ImportJob).order_by(ImportJob.id.desc()).limit(30)).all()
    return render(request, "imports.html", {"jobs": jobs, "selected": request.query_params.get("plateforme", "")})


EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension_src"


@router.get("/extension/autodeal-capture.zip")
def extension_zip(user: User = Depends(current_user)):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(EXTENSION_DIR.rglob("*")):
            if f.is_file():
                z.write(f, "autodeal-capture/" + f.relative_to(EXTENSION_DIR).as_posix())
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="autodeal-capture.zip"'})


@router.get("/imports/modele.csv")
def csv_template(user: User = Depends(current_user)):
    return PlainTextResponse("﻿" + CSV_TEMPLATE, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="modele-import-autodeal.csv"'})


@router.post("/imports/fichier", dependencies=[Depends(csrf_protect)])
async def upload_file(request: Request, platform: str = Form(...), url: str = Form(""),
                      fichier: UploadFile = File(...), db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    platform = _valid_platform(platform)
    limit = settings.max_upload_mb * 1024 * 1024
    content = await fichier.read(limit + 1)
    if len(content) > limit:
        flash(request, f"Fichier trop volumineux (max {settings.max_upload_mb} Mo).", "error")
        return RedirectResponse("/imports", status_code=303)
    if not content:
        flash(request, "Fichier vide.", "error")
        return RedirectResponse("/imports", status_code=303)
    name = (fichier.filename or "import").rsplit("/", 1)[-1][:200]
    job = import_file(db, platform, name, content, url=url.strip() or None, user_id=user.id)
    _flash_job(request, job)
    if job.created_count + job.updated_count == 1 and job.status != "echec":
        lid = db.scalar(select(Listing.id).where(Listing.import_job_id == job.id))
        if lid:
            return RedirectResponse(f"/annonces/{lid}", status_code=303)
    return RedirectResponse("/imports", status_code=303)


@router.post("/imports/texte", dependencies=[Depends(csrf_protect)])
def paste_text(request: Request, platform: str = Form(...), texte: str = Form(...), url: str = Form(""),
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    platform = _valid_platform(platform)
    job = import_text(db, platform, texte[:20_000], url=url.strip() or None, user_id=user.id)
    _flash_job(request, job)
    lid = db.scalar(select(Listing.id).where(Listing.import_job_id == job.id))
    if lid:
        flash(request, "Vérifiez et complétez les champs extraits si besoin (bouton « Modifier »).", "info")
        return RedirectResponse(f"/annonces/{lid}", status_code=303)
    return RedirectResponse("/imports", status_code=303)


def _flash_job(request: Request, job: ImportJob) -> None:
    if job.status == "echec":
        flash(request, "Import échoué : " + ("; ".join(job.errors[:3]) or "aucune annonce reconnue."), "error")
    else:
        msg = f"Import terminé : {job.created_count} ajoutée(s), {job.updated_count} mise(s) à jour"
        if job.skipped_count:
            msg += f", {job.skipped_count} ignorée(s)"
        flash(request, msg + ".", "success" if job.status == "ok" else "warning")
        for e in job.errors[:3]:
            flash(request, e, "warning")


@router.get("/connecteurs")
def connectors_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    counts = dict(db.execute(select(Listing.platform, func.count(Listing.id)).group_by(Listing.platform)).all())
    configs = {c.platform: c for c in db.scalars(select(ConnectorConfig))}
    items = []
    for c in all_connectors():
        cfg = configs.get(c.key)
        status, label = effective_status(c, cfg)
        items.append({"c": c, "cfg": cfg, "count": counts.get(c.key, 0), "status": status, "status_label": label})
    summary = {s.value: sum(1 for i in items if i["status"] == s.value and i["c"].key != "manuel") for s in ConnectorStatus}
    return render(request, "connectors.html", {"items": items, "summary": summary})


@router.post("/connecteurs/{key}/flux", dependencies=[Depends(csrf_protect)])
def configure_feed(key: str, request: Request, feed_url: str = Form(""), feed_format: str = Form("csv"),
                   auth_header_name: str = Form(""), auth_header_value: str = Form(""),
                   authorization_note: str = Form(""), feed_enabled: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(admin_user)):
    key = _valid_platform(key)
    cfg = db.get(ConnectorConfig, key) or ConnectorConfig(platform=key)
    feed_url = feed_url.strip()
    if feed_url:
        try:
            validate_feed_url(feed_url)
        except FeedError as exc:
            flash(request, str(exc), "error")
            return RedirectResponse("/connecteurs", status_code=303)
    enabling = feed_enabled == "on"
    if enabling and not authorization_note.strip():
        flash(request, "Précisez l'autorisation obtenue (contrat, e-mail, conditions de l'API) avant d'activer le flux.", "error")
        return RedirectResponse("/connecteurs", status_code=303)
    cfg.feed_url = feed_url or None
    cfg.feed_format = feed_format if feed_format in {"csv", "json"} else "csv"
    cfg.auth_header_name = auth_header_name.strip()[:80] or None
    if auth_header_value.strip():  # champ vide = conserver le secret existant
        cfg.auth_header_value = auth_header_value.strip()[:500]
    cfg.authorization_note = authorization_note.strip()[:2000] or None
    cfg.feed_enabled = enabling and bool(cfg.feed_url)
    db.add(cfg)
    db.commit()
    flash(request, "Configuration du flux enregistrée.", "success")
    return RedirectResponse("/connecteurs", status_code=303)


@router.post("/connecteurs/{key}/synchroniser", dependencies=[Depends(csrf_protect)])
def sync_now(key: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    key = _valid_platform(key)
    try:
        job = sync_feed(db, key)
        _flash_job(request, job)
    except FeedError as exc:
        flash(request, f"Synchronisation impossible : {exc}", "error")
    return RedirectResponse("/connecteurs", status_code=303)
