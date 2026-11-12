"""Outils partagés par les routes : templates, session, authentification, CSRF."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .analysis.scoring import verdict
from .connectors.registry import all_connectors, platform_name
from .db import get_db
from .models import User
from .security import check_csrf, get_csrf_token

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def fmt_eur(value) -> str:
    if value is None:
        return "—"
    return f"{int(value):,} €".replace(",", " ")


def fmt_int(value) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", " ")


def fmt_pct(value) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f} %".replace(".", ",")


def fmt_date(value) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    s = str(value)
    if len(s) >= 10 and s[4] == "-":
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}"
    return s


templates.env.filters.update(eur=fmt_eur, num=fmt_int, pct=fmt_pct, date=fmt_date, platform=platform_name)
templates.env.globals.update(verdict=verdict, connectors=all_connectors)

STATUS_LABELS = {"nouveau": "Nouveau", "suivi": "Suivi", "ecarte": "Écarté", "achete": "Acheté"}
CT_LABELS = {"ok": "OK", "a_refaire": "À refaire", "contre_visite": "Contre-visite", "inconnu": "Inconnu"}
PRICE_TYPES = {"prix_fixe": "Prix affiché", "enchere_depart": "Mise à prix", "enchere_actuelle": "Enchère actuelle",
               "adjuge": "Adjugé", "estimation": "Estimation"}
templates.env.globals.update(STATUS_LABELS=STATUS_LABELS, CT_LABELS=CT_LABELS, PRICE_TYPES=PRICE_TYPES)


class LoginRequired(Exception):
    pass


def flash(request: Request, message: str, kind: str = "info") -> None:
    msgs = request.session.get("flash", [])
    msgs.append({"msg": message, "kind": kind})
    request.session["flash"] = msgs[-5:]


def render(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    context = dict(ctx or {})
    context.setdefault("user", getattr(request.state, "user", None))
    context["csrf_token"] = get_csrf_token(request.session)
    context["flashes"] = request.session.pop("flash", [])
    context["path"] = request.url.path
    context["request_base"] = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if not user or not user.is_active or request.session.get("pwv") != user.password_hash[-12:]:
        request.session.pop("uid", None)
        raise LoginRequired()
    request.state.user = user
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs.")
    return user


async def csrf_protect(request: Request) -> None:
    form = await request.form()
    token = form.get("csrf_token") or request.headers.get("x-csrf-token")
    if not check_csrf(request.session, token):
        raise HTTPException(status_code=400, detail="Jeton de sécurité invalide. Rechargez la page et réessayez.")
