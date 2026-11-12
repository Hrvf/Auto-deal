"""Socle commun des connecteurs : modèle normalisé, statut, interface."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum


class ConnectorStatus(str, Enum):
    AUTO = "auto"                  # récupération automatique fonctionnelle
    AUTORISATION = "autorisation"  # nécessite un accord / accès API de la plateforme
    MANUEL = "manuel"              # import manuel uniquement

    @property
    def label(self) -> str:
        return {
            "auto": "Automatique",
            "autorisation": "Autorisation requise",
            "manuel": "Import manuel",
        }[self.value]


class ConnectorNotAuthorized(Exception):
    """Levée quand on tente une récupération automatique non autorisée."""


@dataclass
class NormalizedListing:
    platform: str
    external_id: str | None = None
    url: str | None = None
    title: str = ""
    make: str | None = None
    model: str | None = None
    version: str | None = None
    engine: str | None = None
    fuel: str | None = None
    gearbox: str | None = None
    body: str | None = None
    color: str | None = None
    year: int | None = None
    first_registration: str | None = None
    mileage_km: int | None = None
    fiscal_hp: int | None = None
    power_hp: int | None = None
    location: str | None = None
    department: str | None = None
    price: int | None = None
    price_type: str = "prix_fixe"
    price_includes_fees: bool = False
    vat_recoverable: bool = False
    auction_end: datetime | None = None
    seller_type: str | None = None
    damages_text: str | None = None
    ct_status: str = "inconnu"
    is_running: bool | None = None
    maintenance_history: bool | None = None
    market_price_manual: int | None = None
    photos: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def ensure_id(self) -> str:
        """Identifiant stable : id de la plateforme, sinon URL, sinon empreinte."""
        if self.external_id:
            return self.external_id
        basis = self.url or "|".join(
            str(x) for x in (self.title, self.make, self.model, self.year, self.mileage_km, self.price, self.location)
        )
        self.external_id = "h-" + hashlib.sha1(basis.encode()).hexdigest()[:16]
        return self.external_id

    def problems(self) -> list[str]:
        """Champs indispensables manquants (la ligne est quand même importable)."""
        missing = []
        if not (self.make or self.title):
            missing.append("marque/titre")
        if self.price is None:
            missing.append("prix")
        return missing

    def to_model_kwargs(self) -> dict:
        data = asdict(self)
        return data


@dataclass
class ParseResult:
    listings: list[NormalizedListing] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: int = 0


@dataclass(frozen=True)
class PlatformFees:
    """Frais acheteur par défaut (modifiables dans Paramètres)."""

    pct: float = 0.0          # pourcentage du prix (TTC)
    fixed: int = 0            # frais fixes TTC (dossier, etc.)
    note: str = ""


class Connector:
    key: str = ""
    name: str = ""
    website: str = ""
    kind: str = "annonce"  # annonce | enchere
    status: ConnectorStatus = ConnectorStatus.MANUEL
    status_reason: str = ""
    how_to_authorize: str = ""
    how_to_export: str = ""
    default_price_type: str = "prix_fixe"
    default_seller_type: str | None = None
    default_fees: PlatformFees = PlatformFees()
    is_retail_reference: bool = False  # annonces au prix de détail -> servent de comparables
    extra_aliases: dict[str, list[str]] = {}

    # --- Imports manuels -------------------------------------------------
    def parse_file(self, filename: str, content: bytes, url: str | None = None) -> ParseResult:
        from . import parsers

        name = (filename or "").lower()
        if name.endswith((".html", ".htm", ".mhtml")):
            result = parsers.parse_html(content, self, url=url)
        elif name.endswith(".json"):
            result = parsers.parse_json(content, self)
        elif name.endswith((".csv", ".txt", ".tsv")):
            result = parsers.parse_csv(content, self)
        else:
            stripped = content.lstrip()[:1]
            if stripped in (b"{", b"["):
                result = parsers.parse_json(content, self)
            elif stripped == b"<":
                result = parsers.parse_html(content, self, url=url)
            else:
                result = parsers.parse_csv(content, self)
        for item in result.listings:
            self.apply_defaults(item)
        return result

    def parse_text(self, text: str, url: str | None = None) -> ParseResult:
        from . import parsers

        result = parsers.parse_free_text(text, self, url=url)
        for item in result.listings:
            self.apply_defaults(item)
        return result

    def apply_defaults(self, item: NormalizedListing) -> None:
        item.platform = self.key
        if item.price_type == "prix_fixe" and self.default_price_type != "prix_fixe":
            item.price_type = self.default_price_type
        if not item.seller_type and self.default_seller_type:
            item.seller_type = self.default_seller_type
        item.ensure_id()

    # --- Récupération automatique ---------------------------------------
    def auto_fetch(self):
        """Aucune récupération directe sur le site : on passe par un flux autorisé."""
        raise ConnectorNotAuthorized(self.status_reason)

    def describe(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "website": self.website,
            "kind": self.kind,
            "status": self.status.value,
            "status_label": self.status.label,
            "status_reason": self.status_reason,
            "how_to_authorize": self.how_to_authorize,
            "how_to_export": self.how_to_export,
        }
