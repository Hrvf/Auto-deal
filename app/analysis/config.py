"""Paramètres d'analyse (valeurs par défaut + surcharges enregistrées en base)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from sqlalchemy.orm import Session

from ..connectors.registry import all_connectors
from ..models import AppSetting


@dataclass
class GeneralConfig:
    labor_rate: int = 65                 # €/h main-d'œuvre (indicatif)
    carte_grise_cv_rate: float = 58.0    # €/CV : Nouvelle-Aquitaine depuis le 01/03/2026 ; à ajuster selon la région
    carte_grise_fixed: float = 13.76     # taxe fixe 11 € + redevance d'acheminement 2,76 €
    default_fiscal_hp: int = 6
    preparation_cost: int = 150          # nettoyage / préparation esthétique
    ct_cost: int = 85
    transport_auction: int = 150         # rapatriement d'un véhicule acheté aux enchères
    transport_listing: int = 0
    sale_costs: int = 60                 # coût de mise en vente (annonce, photos)
    contingency_pct: float = 0.03        # provision aléas sur le prix d'achat
    resale_negotiation_pct: float = 0.05 # écart prix affiché -> prix réellement obtenu
    vat_regime: str = "particulier"      # particulier | marge (TVA sur marge, marchand)
    target_margin_pct: float = 0.15      # marge visée pour calculer l'enchère maximale

    @classmethod
    def from_dict(cls, data: dict) -> "GeneralConfig":
        cfg = cls()
        for f in fields(cls):
            if f.name in data and data[f.name] is not None:
                try:
                    setattr(cfg, f.name, type(getattr(cfg, f.name))(data[f.name]))
                except (TypeError, ValueError):
                    pass
        if cfg.vat_regime not in {"particulier", "marge"}:
            cfg.vat_regime = "particulier"
        return cfg


@dataclass
class AnalysisConfig:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    fees: dict[str, dict] = field(default_factory=dict)  # plateforme -> {pct, fixed, note}

    def fee_for(self, platform: str) -> dict:
        return self.fees.get(platform, {"pct": 0.0, "fixed": 0, "note": ""})


def default_fees() -> dict[str, dict]:
    return {
        c.key: {"pct": c.default_fees.pct, "fixed": c.default_fees.fixed, "note": c.default_fees.note}
        for c in all_connectors()
    }


def load_config(db: Session) -> AnalysisConfig:
    general_row = db.get(AppSetting, "general")
    fees_row = db.get(AppSetting, "fees")
    fees = default_fees()
    if fees_row and isinstance(fees_row.value, dict):
        for key, val in fees_row.value.items():
            if key in fees and isinstance(val, dict):
                fees[key].update({k: v for k, v in val.items() if k in {"pct", "fixed"}})
    return AnalysisConfig(
        general=GeneralConfig.from_dict(general_row.value if general_row else {}),
        fees=fees,
    )


def save_general(db: Session, cfg: GeneralConfig) -> None:
    row = db.get(AppSetting, "general") or AppSetting(key="general")
    row.value = asdict(cfg)
    db.add(row)


def save_fees(db: Session, fees: dict[str, dict]) -> None:
    row = db.get(AppSetting, "fees") or AppSetting(key="fees")
    row.value = {k: {"pct": float(v["pct"]), "fixed": int(v["fixed"])} for k, v in fees.items()}
    db.add(row)
