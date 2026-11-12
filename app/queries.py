"""Construction des requêtes de recherche/filtrage d'annonces."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .models import Analysis, Listing

SORTS = {
    "score": ("Meilleure note", lambda: Analysis.score.desc().nulls_last()),
    "marge": ("Meilleure marge", lambda: Analysis.margin.desc().nulls_last()),
    "marge_pct": ("Meilleure marge %", lambda: Analysis.margin_pct.desc().nulls_last()),
    "prix_asc": ("Prix croissant", lambda: Listing.price.asc().nulls_last()),
    "prix_desc": ("Prix décroissant", lambda: Listing.price.desc().nulls_last()),
    "km": ("Kilométrage", lambda: Listing.mileage_km.asc().nulls_last()),
    "annee": ("Plus récents", lambda: Listing.year.desc().nulls_last()),
    "fin_enchere": ("Fin d'enchère proche", lambda: Listing.auction_end.asc().nulls_last()),
    "recent": ("Derniers ajoutés", lambda: Listing.first_seen_at.desc()),
}
PAGE_SIZE = 30


def _int(v) -> int | None:
    try:
        return int(str(v).replace(" ", "").replace(" ", "")) if v not in (None, "") else None
    except ValueError:
        return None


@dataclass
class ListingFilters:
    q: str = ""
    platforms: list[str] = field(default_factory=list)
    make: str = ""
    model: str = ""
    fuel: str = ""
    gearbox: str = ""
    price_min: int | None = None
    price_max: int | None = None
    year_min: int | None = None
    year_max: int | None = None
    km_max: int | None = None
    score_min: int | None = None
    margin_min: int | None = None
    department: str = ""
    status: str = ""
    favorite: bool = False
    include_ecarte: bool = False
    sort: str = "score"
    page: int = 1

    @classmethod
    def from_params(cls, params) -> "ListingFilters":
        get = params.get
        platforms = params.getlist("plateforme") if hasattr(params, "getlist") else (get("plateforme") or [])
        f = cls(
            q=(get("q") or "").strip()[:100],
            platforms=[p for p in platforms if p][:10],
            make=(get("marque") or "").strip()[:60],
            model=(get("modele") or "").strip()[:80],
            fuel=(get("energie") or "").strip(),
            gearbox=(get("boite") or "").strip(),
            price_min=_int(get("prix_min")), price_max=_int(get("prix_max")),
            year_min=_int(get("annee_min")), year_max=_int(get("annee_max")),
            km_max=_int(get("km_max")), score_min=_int(get("note_min")), margin_min=_int(get("marge_min")),
            department=(get("dep") or "").strip()[:3],
            status=(get("statut") or "").strip(),
            favorite=get("favoris") in ("1", "on", "true"),
            include_ecarte=get("ecartes") in ("1", "on", "true"),
            sort=get("tri") if get("tri") in SORTS else "score",
            page=max(1, _int(get("page")) or 1),
        )
        return f

    def to_query(self, **override) -> str:
        data = {
            "q": self.q, "plateforme": self.platforms, "marque": self.make, "modele": self.model,
            "energie": self.fuel, "boite": self.gearbox, "prix_min": self.price_min, "prix_max": self.price_max,
            "annee_min": self.year_min, "annee_max": self.year_max, "km_max": self.km_max,
            "note_min": self.score_min, "marge_min": self.margin_min, "dep": self.department,
            "statut": self.status, "favoris": "1" if self.favorite else "", "ecartes": "1" if self.include_ecarte else "",
            "tri": self.sort, "page": self.page,
        }
        data.update(override)
        clean = {k: v for k, v in data.items() if v is not None and v != "" and v != []}
        if clean.get("page") == 1:
            clean.pop("page")
        if clean.get("tri") == "score":
            clean.pop("tri")
        return urlencode(clean, doseq=True)

    def active_count(self) -> int:
        keys = ("q", "platforms", "make", "model", "fuel", "gearbox", "price_min", "price_max", "year_min",
                "year_max", "km_max", "score_min", "margin_min", "department", "status", "favorite")
        return sum(1 for k in keys if getattr(self, k) not in (None, "", [], False))


def build_query(f: ListingFilters) -> Select:
    q = select(Listing).outerjoin(Analysis).where(Listing.is_active.is_(True))
    if f.q:
        like = f"%{f.q.lower()}%"
        q = q.where(or_(func.lower(Listing.title).like(like), func.lower(Listing.version).like(like),
                        func.lower(Listing.make).like(like), func.lower(Listing.model).like(like)))
    if f.platforms:
        q = q.where(Listing.platform.in_(f.platforms))
    if f.make:
        q = q.where(func.lower(Listing.make) == f.make.lower())
    if f.model:
        q = q.where(func.lower(Listing.model).like(f"%{f.model.lower()}%"))
    if f.fuel:
        q = q.where(Listing.fuel == f.fuel)
    if f.gearbox:
        q = q.where(Listing.gearbox == f.gearbox)
    if f.price_min is not None:
        q = q.where(Listing.price >= f.price_min)
    if f.price_max is not None:
        q = q.where(Listing.price <= f.price_max)
    if f.year_min is not None:
        q = q.where(Listing.year >= f.year_min)
    if f.year_max is not None:
        q = q.where(Listing.year <= f.year_max)
    if f.km_max is not None:
        q = q.where(Listing.mileage_km <= f.km_max)
    if f.score_min is not None:
        q = q.where(Analysis.score >= f.score_min)
    if f.margin_min is not None:
        q = q.where(Analysis.margin >= f.margin_min)
    if f.department:
        q = q.where(Listing.department == f.department.zfill(2))
    if f.status:
        q = q.where(Listing.status == f.status)
    elif not f.include_ecarte:
        q = q.where(Listing.status != "ecarte")
    if f.favorite:
        q = q.where(Listing.favorite.is_(True))
    return q


def search(db: Session, f: ListingFilters, page_size: int = PAGE_SIZE) -> tuple[list[Listing], int]:
    base = build_query(f)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.options(selectinload(Listing.analysis))
        .order_by(SORTS[f.sort][1](), Listing.id.desc())
        .offset((f.page - 1) * page_size).limit(page_size)
    ).all()
    return list(rows), total


def distinct_makes(db: Session) -> list[str]:
    return [m for m in db.scalars(select(Listing.make).where(Listing.make.is_not(None)).distinct().order_by(Listing.make)) if m]
