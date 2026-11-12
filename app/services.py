"""Services métier : enregistrement des imports, synchronisation des flux autorisés."""
from __future__ import annotations

from dataclasses import fields as dc_fields
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analysis.engine import analyze_related
from .connectors.base import NormalizedListing, ParseResult
from .connectors.registry import get_connector
from .models import ConnectorConfig, ImportJob, Listing, utcnow

# Champs que l'utilisateur modifie lui-même : jamais écrasés par un réimport.
USER_FIELDS = {"notes", "favorite", "status", "market_price_manual"}
_LISTING_FIELDS = {f.name for f in dc_fields(NormalizedListing)}

MAX_FEED_BYTES = 20 * 1024 * 1024


def save_parse_result(db: Session, platform: str, source: str, result: ParseResult,
                      filename: str | None = None, user_id: int | None = None) -> ImportJob:
    job = ImportJob(platform=platform, source=source, filename=filename, user_id=user_id,
                    errors=list(result.errors[:200]), skipped_count=result.skipped)
    db.add(job)
    db.flush()
    pairs: set[tuple[str, str]] = set()
    seen: set[str] = set()
    for item in result.listings:
        ext = item.ensure_id()
        if ext in seen:
            job.skipped_count += 1
            continue
        seen.add(ext)
        existing = db.scalar(select(Listing).where(Listing.platform == platform, Listing.external_id == ext))
        data = {k: v for k, v in item.to_model_kwargs().items() if k in _LISTING_FIELDS}
        data["platform"] = platform
        if existing:
            for key, value in data.items():
                if key in USER_FIELDS and getattr(existing, key):
                    continue
                if value in (None, "", []) and getattr(existing, key) not in (None, "", []):
                    continue  # ne pas effacer une donnée connue par une donnée absente
                setattr(existing, key, value)
            existing.is_active = True
            existing.import_job_id = job.id
            job.updated_count += 1
        else:
            db.add(Listing(**data, import_job_id=job.id))
            job.created_count += 1
        if item.make and item.model:
            pairs.add((item.make, item.model))
    db.flush()
    analyze_related(db, pairs)
    if not result.listings:
        job.status = "echec"
    elif result.errors:
        job.status = "partiel"
    db.commit()
    return job


def import_file(db: Session, platform: str, filename: str, content: bytes, url: str | None = None,
                user_id: int | None = None) -> ImportJob:
    connector = get_connector(platform)
    result = connector.parse_file(filename, content, url=url)
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    source = {"htm": "html", "html": "html", "json": "json"}.get(ext, "csv")
    return save_parse_result(db, platform, source, result, filename=filename, user_id=user_id)


def import_text(db: Session, platform: str, text: str, url: str | None = None, user_id: int | None = None) -> ImportJob:
    connector = get_connector(platform)
    result = connector.parse_text(text, url=url)
    return save_parse_result(db, platform, "texte", result, filename=None, user_id=user_id)


class FeedError(Exception):
    pass


def validate_feed_url(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.netloc:
        raise FeedError("L'URL du flux doit commencer par https://")
    return url


def sync_feed(db: Session, platform: str, client: httpx.Client | None = None) -> ImportJob:
    """Télécharge le flux autorisé configuré pour une plateforme et l'importe."""
    cfg = db.get(ConnectorConfig, platform)
    if not cfg or not cfg.feed_enabled or not cfg.feed_url:
        raise FeedError("Aucun flux autorisé n'est configuré et activé pour ce connecteur.")
    validate_feed_url(cfg.feed_url)
    headers = {"User-Agent": "AutoDealComparator/1.0 (flux autorise)"}
    if cfg.auth_header_name and cfg.auth_header_value:
        headers[cfg.auth_header_name] = cfg.auth_header_value
    own_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    try:
        resp = client.get(cfg.feed_url, headers=headers)
        if resp.status_code != 200:
            raise FeedError(f"Le flux a répondu HTTP {resp.status_code}.")
        content = resp.content
        if len(content) > MAX_FEED_BYTES:
            raise FeedError("Flux trop volumineux (> 20 Mo).")
    except httpx.HTTPError as exc:
        cfg.last_sync_at = utcnow()
        cfg.last_sync_status = f"Erreur réseau : {exc.__class__.__name__}"
        db.commit()
        raise FeedError(cfg.last_sync_status) from exc
    except FeedError as exc:
        cfg.last_sync_at = utcnow()
        cfg.last_sync_status = str(exc)
        db.commit()
        raise
    finally:
        if own_client:
            client.close()
    connector = get_connector(platform)
    filename = f"flux.{cfg.feed_format}"
    result = connector.parse_file(filename, content)
    job = save_parse_result(db, platform, "flux", result, filename=cfg.feed_url[:255])
    cfg.last_sync_at = utcnow()
    cfg.last_sync_status = f"OK : {job.created_count} créées, {job.updated_count} mises à jour"
    db.commit()
    return job


# --------------------------------------------------------------------------
# Capture depuis l'extension navigateur (page consultée par l'utilisateur)
# --------------------------------------------------------------------------
HOST_PLATFORMS = {
    "alcopa-auction.fr": "alcopa",
    "leboncoin.fr": "leboncoin",
    "vpauto.fr": "vpauto",
    "encheres-domaine.gouv.fr": "domaine",
    "bca.fr": "bca",
    "bca.com": "bca",
    "lacentrale.fr": "lacentrale",
}
MAX_CAPTURE_HTML = 6 * 1024 * 1024
MAX_CAPTURE_TEXT = 300_000


class CaptureError(Exception):
    pass


def platform_from_url(url: str | None) -> str | None:
    host = (urlparse(url or "").hostname or "").lower()
    for domain, key in HOST_PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return key
    return None


def capture_page(db: Session, *, url: str, html: str | None, text: str | None, title: str | None,
                 user_id: int | None, platform: str | None = None) -> tuple[ImportJob, Listing | None]:
    from .connectors import parsers
    from .connectors.base import ParseResult

    if not url or not url.startswith(("http://", "https://")):
        raise CaptureError("URL de page invalide.")
    platform = platform or platform_from_url(url)
    if not platform:
        raise CaptureError("Ce site n'est pas une plateforme prise en charge.")
    connector = get_connector(platform)
    html = (html or "")[:MAX_CAPTURE_HTML]
    text = (text or "")[:MAX_CAPTURE_TEXT]

    result = connector.parse_file("capture.html", html.encode(), url=url) if html else ParseResult()
    from_text = parsers._extract_from_text(text) if text else {}
    if not result.listings and (title or text):
        # Pas de données structurées : on reconstruit à partir du titre et du texte visible.
        values = dict(from_text)
        values["title"] = title
        values["url"] = url
        values["damages_text"] = parsers.extract_damage_section(text)
        item = parsers.build_listing(values, connector, raw={"source": "capture (texte visible)"})
        connector.apply_defaults(item)
        result = ParseResult(listings=[] if "marque/titre" in item.problems() else [item],
                             errors=[] if item.price else ["Prix non trouvé : à compléter sur la fiche."])
        if not result.listings:
            result.errors = ["Aucun véhicule reconnu sur cette page."]
    elif result.listings and from_text:
        # Compléter les champs absents des données structurées avec le texte visible.
        item = result.listings[0]
        weak = str(item.raw.get("source", "")).startswith("balises meta")
        if title and (weak or not item.make):
            # Données structurées absentes : le titre affiché (h1) est plus fiable que <title>.
            from .connectors.normalize import split_title
            item.title = title[:300]
            mk, md = split_title(title)
            item.make, item.model = item.make or mk, item.model or md
            if weak:
                item.make, item.model = mk or item.make, md or item.model
        filler = parsers.build_listing({**from_text, "title": item.title or title}, connector)
        for field_name in ("year", "first_registration", "mileage_km", "fiscal_hp", "power_hp", "fuel", "gearbox",
                           "price", "department", "is_running"):
            if getattr(item, field_name) in (None, "") and getattr(filler, field_name) not in (None, ""):
                setattr(item, field_name, getattr(filler, field_name))
        if item.ct_status == "inconnu":
            item.ct_status = filler.ct_status
        if platform != "leboncoin" and (weak or not item.damages_text):
            item.damages_text = parsers.extract_damage_section(text) or item.damages_text
        result.errors = [e for e in result.errors if not (e.startswith("Prix") and item.price)]
    for item in result.listings:
        item.url = url
    job = save_parse_result(db, platform, "capture", result, filename=url[:255], user_id=user_id)
    listing = None
    if result.listings:
        listing = db.scalar(select(Listing).where(Listing.platform == platform,
                                                  Listing.external_id == result.listings[0].external_id))
    return job, listing
