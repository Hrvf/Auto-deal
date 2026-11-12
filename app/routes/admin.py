"""Paramètres d'analyse et gestion des utilisateurs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analysis.config import GeneralConfig, load_config, save_fees, save_general
from ..analysis.engine import analyze_all
from ..connectors.registry import all_connectors
from ..db import get_db
from ..models import User
from ..security import hash_password, verify_password
from ..web import admin_user, csrf_protect, current_user, flash, render

router = APIRouter()


@router.get("/parametres")
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    cfg = load_config(db)
    users = db.scalars(select(User).order_by(User.id)).all() if user.is_admin else []
    return render(request, "settings.html", {"cfg": cfg, "users": users, "connectors_list": all_connectors()})


def _float(v, default: float) -> float:
    try:
        return float(str(v).replace(",", ".").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


@router.post("/parametres/analyse", dependencies=[Depends(csrf_protect)])
async def save_analysis_settings(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    form = await request.form()
    cfg = load_config(db)
    g = cfg.general
    data = {}
    for name in ("labor_rate", "default_fiscal_hp", "preparation_cost", "ct_cost", "transport_auction",
                 "transport_listing", "sale_costs"):
        data[name] = max(0, int(_float(form.get(name), getattr(g, name))))
    for name in ("carte_grise_cv_rate", "carte_grise_fixed"):
        data[name] = max(0.0, _float(form.get(name), getattr(g, name)))
    for name in ("contingency_pct", "resale_negotiation_pct", "target_margin_pct"):
        val = _float(form.get(name), getattr(g, name) * 100) / 100
        data[name] = min(max(val, 0.0), 0.9)
    data["vat_regime"] = form.get("vat_regime") if form.get("vat_regime") in {"particulier", "marge"} else g.vat_regime
    save_general(db, GeneralConfig.from_dict(data))
    fees = {}
    for c in all_connectors():
        pct = min(max(_float(form.get(f"fee_pct_{c.key}"), cfg.fee_for(c.key)["pct"] * 100) / 100, 0.0), 0.5)
        fixed = max(0, int(_float(form.get(f"fee_fixed_{c.key}"), cfg.fee_for(c.key)["fixed"])))
        fees[c.key] = {"pct": pct, "fixed": fixed}
    save_fees(db, fees)
    db.flush()
    n = analyze_all(db)
    db.commit()
    flash(request, f"Paramètres enregistrés, {n} annonce(s) réanalysée(s).", "success")
    return RedirectResponse("/parametres", status_code=303)


@router.post("/parametres/utilisateurs", dependencies=[Depends(csrf_protect)])
def create_user(request: Request, email: str = Form(...), display_name: str = Form(""), password: str = Form(...),
                role: str = Form("membre"), db: Session = Depends(get_db), user: User = Depends(admin_user)):
    email = email.strip().lower()
    if "@" not in email:
        flash(request, "Adresse e-mail invalide.", "error")
    elif db.scalar(select(User).where(func.lower(User.email) == email)):
        flash(request, "Un compte existe déjà avec cette adresse.", "error")
    else:
        try:
            db.add(User(email=email, display_name=display_name.strip()[:120], password_hash=hash_password(password),
                        role="admin" if role == "admin" else "membre"))
            db.commit()
            flash(request, f"Compte {email} créé.", "success")
        except ValueError as exc:
            flash(request, str(exc), "error")
    return RedirectResponse("/parametres#utilisateurs", status_code=303)


@router.post("/parametres/utilisateurs/{uid}/activer", dependencies=[Depends(csrf_protect)])
def toggle_user(uid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    target = db.get(User, uid)
    if target and target.id != user.id:
        target.is_active = not target.is_active
        db.commit()
        flash(request, f"Compte {target.email} {'réactivé' if target.is_active else 'désactivé'}.", "success")
    return RedirectResponse("/parametres#utilisateurs", status_code=303)


@router.post("/parametres/mot-de-passe", dependencies=[Depends(csrf_protect)])
def change_password(request: Request, current: str = Form(...), new: str = Form(...), new2: str = Form(...),
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not verify_password(current, user.password_hash):
        flash(request, "Mot de passe actuel incorrect.", "error")
    elif new != new2:
        flash(request, "Les nouveaux mots de passe ne correspondent pas.", "error")
    else:
        try:
            user.password_hash = hash_password(new)
            db.commit()
            request.session["pwv"] = user.password_hash[-12:]
            flash(request, "Mot de passe modifié.", "success")
        except ValueError as exc:
            flash(request, str(exc), "error")
    return RedirectResponse("/parametres#compte", status_code=303)
