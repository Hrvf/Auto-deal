"""Connexion, déconnexion et création du premier compte administrateur."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User, utcnow
from ..security import DUMMY_HASH, hash_password, login_limiter, verify_password
from ..web import csrf_protect, flash, render

router = APIRouter()


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "inconnu"


def _setup_allowed(db: Session) -> bool:
    return (db.scalar(select(func.count(User.id))) or 0) == 0


def login_session(request: Request, user: User) -> None:
    request.session.clear()  # nouvelle session : évite la fixation de session
    request.session["uid"] = user.id
    request.session["pwv"] = user.password_hash[-12:]


@router.get("/connexion")
def login_page(request: Request, db: Session = Depends(get_db)):
    if _setup_allowed(db):
        return RedirectResponse("/installation", status_code=303)
    return render(request, "login.html", {"next": request.query_params.get("suite", "/")})


@router.post("/connexion", dependencies=[Depends(csrf_protect)])
def login_submit(request: Request, email: str = Form(...), password: str = Form(...),
                 suite: str = Form("/"), db: Session = Depends(get_db)):
    key = _client_key(request)
    if login_limiter.is_blocked(key):
        flash(request, "Trop de tentatives. Réessayez dans 15 minutes.", "error")
        return render(request, "login.html", {"next": suite, "email": email}, status_code=429)
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        login_limiter.record_failure(key)
        flash(request, "Identifiants incorrects.", "error")
        return render(request, "login.html", {"next": suite, "email": email}, status_code=401)
    login_limiter.reset(key)
    user.last_login_at = utcnow()
    db.commit()
    login_session(request, user)
    target = suite if suite.startswith("/") and not suite.startswith("//") else "/"
    return RedirectResponse(target, status_code=303)


@router.post("/deconnexion", dependencies=[Depends(csrf_protect)])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/connexion", status_code=303)


@router.get("/installation")
def setup_page(request: Request, db: Session = Depends(get_db)):
    if not _setup_allowed(db):
        return RedirectResponse("/connexion", status_code=303)
    return render(request, "setup.html", {"needs_token": bool(os.getenv("SETUP_TOKEN")) or settings.env == "production"})


@router.post("/installation", dependencies=[Depends(csrf_protect)])
def setup_submit(request: Request, email: str = Form(...), display_name: str = Form(""),
                 password: str = Form(...), password2: str = Form(...), setup_token: str = Form(""),
                 db: Session = Depends(get_db)):
    if not _setup_allowed(db):
        return RedirectResponse("/connexion", status_code=303)
    expected = os.getenv("SETUP_TOKEN", "")
    if settings.env == "production" and not expected:
        flash(request, "En production, créez le premier compte avec la commande « python -m app.cli creer-admin » "
                       "ou définissez SETUP_TOKEN.", "error")
        return render(request, "setup.html", {"needs_token": True}, status_code=400)
    if expected and not hmac.compare_digest(expected, setup_token):
        flash(request, "Jeton d'installation incorrect.", "error")
        return render(request, "setup.html", {"needs_token": True}, status_code=403)
    if password != password2:
        flash(request, "Les deux mots de passe ne correspondent pas.", "error")
        return render(request, "setup.html", {"needs_token": bool(expected), "email": email}, status_code=400)
    try:
        pwd_hash = hash_password(password)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return render(request, "setup.html", {"needs_token": bool(expected), "email": email}, status_code=400)
    if "@" not in email:
        flash(request, "Adresse e-mail invalide.", "error")
        return render(request, "setup.html", {"needs_token": bool(expected)}, status_code=400)
    user = User(email=email.strip().lower(), display_name=display_name.strip()[:120], password_hash=pwd_hash, role="admin")
    db.add(user)
    db.commit()
    login_session(request, user)
    flash(request, "Compte administrateur créé. Bienvenue !", "success")
    return RedirectResponse("/", status_code=303)
