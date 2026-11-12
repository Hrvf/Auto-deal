"""Configuration de l'application, lue depuis les variables d'environnement."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "oui", "on"}


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("AUTODEAL_ENV", "development"))
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'autodeal.db'}"
        )
    )
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", ""))
    # Cookies "Secure" : obligatoire dès que le site est servi en HTTPS.
    https_only: bool = field(default_factory=lambda: _bool(os.getenv("HTTPS_ONLY"), False))
    # Mode privé : toutes les pages exigent une connexion. Passer à false
    # rendra publiques les pages marquées comme telles (évolution future).
    private_mode: bool = field(default_factory=lambda: _bool(os.getenv("PRIVATE_MODE"), True))
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "15")))
    session_max_age: int = field(default_factory=lambda: int(os.getenv("SESSION_MAX_AGE", str(60 * 60 * 12))))

    def __post_init__(self) -> None:
        if not self.secret_key:
            if self.env == "production":
                raise RuntimeError("SECRET_KEY doit être défini en production.")
            # Clé éphémère en développement : les sessions sont perdues au redémarrage.
            self.secret_key = secrets.token_urlsafe(48)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
