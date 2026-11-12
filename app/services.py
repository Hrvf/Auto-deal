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
