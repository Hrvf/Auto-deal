"""Point d'entrée de l'application AutoDeal Comparator."""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import init_db
from .routes import admin, api, auth, imports, listings
from .web import LoginRequired, render

STATIC_DIR = Path(__file__).parent / "static"

CSP = ("default-src 'self'; img-src 'self' https: data:; style-src 'self'; script-src 'self'; "
       "font-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'")


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if settings.https_only:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if not request.url.path.startswith("/static"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


EXTENSION_ORIGIN = re.compile(r"^(chrome-extension://[a-p]{32}|moz-extension://[0-9a-f-]{36})$")
EXTENSION_PATHS = ("/api/moi", "/api/capture")


class ExtensionCORS(BaseHTTPMiddleware):
    """Autorise uniquement les extensions de navigateur à appeler les routes à jeton (jamais les sites web).

    Ces routes n'acceptent que le jeton personnel (pas de cookie) : il n'y a donc pas de risque CSRF."""

    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin", "")
        allowed = request.url.path in EXTENSION_PATHS and bool(EXTENSION_ORIGIN.match(origin))
        if request.method == "OPTIONS" and allowed:
            return Response(status_code=204, headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            })
        response = await call_next(request)
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="AutoDeal Comparator", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(ExtensionCORS)
    app.add_middleware(
        SessionMiddleware, secret_key=settings.secret_key, session_cookie="autodeal_session",
        max_age=settings.session_max_age, same_site="lax", https_only=settings.https_only,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    for r in (auth.router, listings.router, imports.router, admin.router, api.router):
        app.include_router(r)

    @app.get("/sante", include_in_schema=False)
    def health():
        return {"statut": "ok"}

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Authentification requise."}, status_code=401)
        target = request.url.path
        if request.url.query:
            target += "?" + request.url.query
        from urllib.parse import quote
        return RedirectResponse(f"/connexion?suite={quote(target)}", status_code=303)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render(request, "error.html", {"code": exc.status_code, "detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Requête invalide."}, status_code=422)
        return render(request, "error.html", {"code": 422, "detail": "Formulaire incomplet ou invalide."}, status_code=422)

    return app


app = create_app()
