"""Frais d'acquisition, coût de revient et marge."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import AnalysisConfig

VAT_RATE = 0.20


@dataclass
class CostResult:
    items: list[dict] = field(default_factory=list)
    purchase_fees: int = 0
    total_cost: int = 0          # coût de revient (réparations au milieu de fourchette)
    vat_on_margin: int = 0
    margin: int | None = None
    margin_pct: float | None = None
    margin_worst: int | None = None  # avec réparations hautes


def carte_grise(cfg: AnalysisConfig, fiscal_hp: int | None, age: int | None) -> int:
    hp = fiscal_hp or cfg.general.default_fiscal_hp
    regional = hp * cfg.general.carte_grise_cv_rate
    if age is not None and age >= 10:
        regional *= 0.5  # réduction de 50 % pour les véhicules de plus de 10 ans
    return int(round(regional + cfg.general.carte_grise_fixed))


def platform_fees(cfg: AnalysisConfig, platform: str, price: int, includes_fees: bool) -> int:
    if includes_fees:
        return 0
    fee = cfg.fee_for(platform)
    return int(round(price * float(fee.get("pct", 0)) + int(fee.get("fixed", 0))))


def compute(cfg: AnalysisConfig, *, platform: str, kind: str, price: int, includes_fees: bool,
            fiscal_hp: int | None, age: int | None, ct_status: str,
            repairs_low: int, repairs_high: int, resale: int | None) -> CostResult:
    g = cfg.general
    res = CostResult()
    fees = platform_fees(cfg, platform, price, includes_fees)
    res.purchase_fees = fees
    repairs_mid = int(round((repairs_low + repairs_high) / 2))
    cg = carte_grise(cfg, fiscal_hp, age)
    transport = g.transport_auction if kind == "enchere" else g.transport_listing
    contingency = int(round(price * g.contingency_pct))

    def add(label: str, amount: int, note: str = "") -> None:
        res.items.append({"label": label, "amount": int(amount), "note": note})

    add("Prix d'achat", price, "frais inclus" if includes_fees else "")
    if fees:
        f = cfg.fee_for(platform)
        add("Frais acheteur plateforme", fees, f"{float(f.get('pct', 0)) * 100:.1f} % + {int(f.get('fixed', 0))} €")
    add("Carte grise", cg, f"{fiscal_hp or g.default_fiscal_hp} CV × {g.carte_grise_cv_rate:g} €"
        + (" (−50 %, + de 10 ans)" if age is not None and age >= 10 else "") + " + taxes fixes"
        + ("" if fiscal_hp else " — puissance fiscale supposée"))
    if transport:
        add("Transport", transport)
    if ct_status in ("a_refaire", "inconnu"):
        add("Contrôle technique", g.ct_cost, "à refaire" if ct_status == "a_refaire" else "statut inconnu")
    add("Réparations estimées", repairs_mid, f"milieu de fourchette {repairs_low}–{repairs_high} €")
    add("Préparation esthétique", g.preparation_cost)
    add("Frais de revente", g.sale_costs)
    if contingency:
        add("Provision aléas", contingency, f"{g.contingency_pct * 100:.0f} % du prix")

    res.total_cost = sum(i["amount"] for i in res.items)
    if resale:
        if g.vat_regime == "marge":
            base = resale - price
            res.vat_on_margin = int(round(max(0, base) * VAT_RATE / (1 + VAT_RATE)))
        res.margin = resale - res.total_cost - res.vat_on_margin
        res.margin_pct = round(res.margin / res.total_cost, 4) if res.total_cost else None
        res.margin_worst = res.margin - (repairs_high - repairs_mid)
    return res


def max_bid(cfg: AnalysisConfig, *, platform: str, kind: str, fiscal_hp: int | None, age: int | None,
            ct_status: str, repairs_low: int, repairs_high: int, resale: int | None) -> int | None:
    """Prix d'achat maximal permettant d'atteindre la marge visée (recherche dichotomique)."""
    if not resale:
        return None
    target = cfg.general.target_margin_pct
    lo, hi = 0, resale
    best = None
    for _ in range(30):
        mid = (lo + hi) // 2
        r = compute(cfg, platform=platform, kind=kind, price=mid, includes_fees=False, fiscal_hp=fiscal_hp,
                    age=age, ct_status=ct_status, repairs_low=repairs_low, repairs_high=repairs_high, resale=resale)
        if r.margin_pct is not None and r.margin_pct >= target:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
        if lo > hi:
            break
    return int(best // 50 * 50) if best else None
