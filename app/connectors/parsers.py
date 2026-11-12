"""Parseurs d'import : CSV, JSON, page HTML enregistrée, texte collé."""
from __future__ import annotations

import csv
import io
import json
import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any

from .base import NormalizedListing, ParseResult
from .normalize import (
    clean_str,
    department_from_postcode,
    norm_key,
    normalize_ct,
    normalize_fuel,
    normalize_gearbox,
    normalize_make,
    normalize_model,
    parse_bool,
    parse_date,
    parse_datetime,
    parse_int,
    parse_km,
    parse_price,
    parse_year,
    split_title,
)

if TYPE_CHECKING:
    from .base import Connector

MAX_ROWS = 20_000

# Champ canonique -> en-têtes acceptés (comparés après normalisation)
FIELD_ALIASES: dict[str, list[str]] = {
    "external_id": ["id", "external_id", "reference", "ref", "numero de lot", "n de lot", "lot", "numero", "list_id", "identifiant"],
    "url": ["url", "lien", "link", "adresse", "page"],
    "title": ["titre", "title", "intitule", "designation", "libelle", "subject", "annonce"],
    "make": ["marque", "make", "brand", "constructeur"],
    "model": ["modele", "model", "gamme"],
    "version": ["version", "finition", "variante"],
    "engine": ["motorisation", "moteur", "engine", "cylindree"],
    "fuel": ["energie", "carburant", "fuel", "energy", "type de carburant"],
    "gearbox": ["boite", "boite de vitesse", "boite de vitesses", "transmission", "gearbox", "bv"],
    "body": ["carrosserie", "body", "type de vehicule", "silhouette"],
    "color": ["couleur", "color", "colour", "teinte"],
    "year": ["annee", "year", "millesime", "annee modele", "annee du modele"],
    "first_registration": ["mise en circulation", "date de mise en circulation", "1ere mise en circulation",
                           "premiere mise en circulation", "mec", "date mec", "first registration", "regdate"],
    "mileage_km": ["kilometrage", "km", "mileage", "kilometrage compteur", "kms", "compteur", "kilometres"],
    "fiscal_hp": ["puissance fiscale", "cv", "chevaux fiscaux", "cv fiscaux", "horse power fiscal"],
    "power_hp": ["puissance", "puissance din", "ch", "power", "puissance ch", "chevaux"],
    "location": ["ville", "localisation", "lieu", "site", "location", "lieu de vente", "centre", "city"],
    "postal_code": ["code postal", "cp", "zipcode", "zip", "postcode"],
    "department": ["departement", "dept", "dep"],
    "price": ["prix", "price", "mise a prix", "prix de depart", "enchere actuelle", "adjudication",
              "montant", "prix de vente", "prix ttc", "derniere enchere", "offre actuelle"],
    "price_type": ["type de prix", "price type"],
    "auction_end": ["date de vente", "fin enchere", "fin des encheres", "date fin", "date de fin", "auction end", "vente le"],
    "seller_type": ["type de vendeur", "vendeur", "seller", "seller type"],
    "damages_text": ["dommages", "frais de remise en etat", "observations", "defauts", "commentaires",
                     "etat", "remarques", "expertise", "damages", "description", "frais estimes"],
    "ct_status": ["controle technique", "ct", "statut ct", "technical inspection"],
    "is_running": ["roulant", "running", "vehicule roulant"],
    "maintenance_history": ["carnet", "carnet d entretien", "historique entretien", "factures"],
    "vat_recoverable": ["tva recuperable", "tva", "vat", "vat recoverable"],
    "market_price_manual": ["cote", "cote argus", "prix marche", "market price", "cote lacentrale"],
    "photos": ["photo", "photos", "image", "images", "visuel"],
}


def _alias_index(connector: "Connector") -> dict[str, str]:
    index: dict[str, str] = {}
    for canon, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            index[norm_key(alias)] = canon
    for canon, aliases in (connector.extra_aliases or {}).items():
        for alias in aliases:
            index[norm_key(alias)] = canon
    return index


def map_headers(headers: list[str], connector: "Connector") -> dict[str, str]:
    """En-tête d'origine -> champ canonique (seulement les colonnes reconnues)."""
    index = _alias_index(connector)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for h in headers:
        canon = index.get(norm_key(h or ""))
        if canon and canon not in used:
            mapping[h] = canon
            used.add(canon)
    return mapping


def build_listing(values: dict[str, Any], connector: "Connector", raw: dict | None = None) -> NormalizedListing:
    """Construit une annonce normalisée à partir d'un dictionnaire de champs canoniques."""
    title = clean_str(values.get("title")) or ""
    make = normalize_make(values.get("make"))
    model = normalize_model(values.get("model"))
    if not make or not model:
        t_make, t_model = split_title(title)
        make = make or t_make
        model = model or t_model
    if not title:
        title = " ".join(x for x in (make, model, clean_str(values.get("version"))) if x)

    first_reg = parse_date(values.get("first_registration"))
    year = parse_year(values.get("year")) or (int(first_reg[:4]) if first_reg else None)
    version = clean_str(values.get("version"))
    engine = clean_str(values.get("engine"))
    fuel = normalize_fuel(values.get("fuel")) or normalize_fuel(" ".join(x for x in (engine, version, title) if x))
    gearbox = normalize_gearbox(values.get("gearbox")) or normalize_gearbox(" ".join(x for x in (version, title) if x))

    department = clean_str(values.get("department"))
    if department:
        department = department.zfill(2)[:3]
    else:
        department = department_from_postcode(values.get("postal_code")) or department_from_postcode(values.get("location"))

    photos = values.get("photos") or []
    if isinstance(photos, str):
        photos = [p.strip() for p in re.split(r"[|,;\s]+", photos) if p.strip().startswith("http")]

    price_type = clean_str(values.get("price_type")) or "prix_fixe"
    if price_type not in {"prix_fixe", "enchere_depart", "enchere_actuelle", "adjuge", "estimation"}:
        price_type = "prix_fixe"

    seller = clean_str(values.get("seller_type"))
    seller_type = None
    if seller:
        k = norm_key(seller)
        seller_type = "pro" if ("pro" in k or "garage" in k or "concession" in k) else ("particulier" if "part" in k else None)

    url = clean_str(values.get("url"))
    if url and not url.startswith(("http://", "https://")):
        url = None

    item = NormalizedListing(
        platform=connector.key,
        external_id=clean_str(values.get("external_id")),
        url=url,
        title=title[:300],
        make=make,
        model=model,
        version=version,
        engine=engine,
        fuel=fuel,
        gearbox=gearbox,
        body=clean_str(values.get("body")),
        color=clean_str(values.get("color")),
        year=year,
        first_registration=first_reg,
        mileage_km=parse_km(values.get("mileage_km")),
        fiscal_hp=parse_int(values.get("fiscal_hp")),
        power_hp=parse_int(values.get("power_hp")),
        location=clean_str(values.get("location")),
        department=department,
        price=parse_price(values.get("price")),
        price_type=price_type,
        vat_recoverable=bool(parse_bool(values.get("vat_recoverable"))),
        auction_end=parse_datetime(values.get("auction_end")),
        seller_type=seller_type,
        damages_text=clean_str(values.get("damages_text")),
        ct_status=normalize_ct(values.get("ct_status")),
        is_running=parse_bool(values.get("is_running")),
        maintenance_history=parse_bool(values.get("maintenance_history")),
        market_price_manual=parse_price(values.get("market_price_manual")),
        photos=list(photos)[:20],
        raw=raw or {},
    )
    return item


# --------------------------------------------------------------------- CSV
def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def parse_csv(content: bytes, connector: "Connector") -> ParseResult:
    result = ParseResult()
    text = _decode(content)
    if not text.strip():
        result.errors.append("Fichier vide.")
        return result
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = reader.fieldnames or []
    mapping = map_headers(headers, connector)
    if not mapping:
        result.errors.append(
            "Aucune colonne reconnue. En-têtes trouvés : " + ", ".join(h for h in headers if h)[:300]
        )
        return result
    if not ({"make", "title"} & set(mapping.values())):
        result.errors.append("Colonne « marque » ou « titre » introuvable : import impossible.")
        return result
    for line_no, row in enumerate(reader, start=2):
        if line_no > MAX_ROWS + 1:
            result.errors.append(f"Limite de {MAX_ROWS} lignes atteinte, la suite est ignorée.")
            break
        values = {canon: row.get(h) for h, canon in mapping.items()}
        if not any(v for v in values.values()):
            result.skipped += 1
            continue
        raw = {k: v for k, v in row.items() if k}
        item = build_listing(values, connector, raw=raw)
        missing = item.problems()
        if "marque/titre" in missing:
            result.skipped += 1
            result.errors.append(f"Ligne {line_no} ignorée : marque et titre absents.")
            continue
        result.listings.append(item)
    return result


# -------------------------------------------------------------------- JSON
def _records_from_json(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        for key in ("items", "results", "data", "listings", "annonces", "vehicles", "lots", "ads"):
            if isinstance(data.get(key), list):
                return [d for d in data[key] if isinstance(d, dict)]
        return [data]
    return []


def _flatten(d: dict, prefix: str = "") -> dict:
    out: dict = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, ""))
        else:
            out[key] = v
    return out


def parse_json(content: bytes, connector: "Connector") -> ParseResult:
    result = ParseResult()
    try:
        data = json.loads(_decode(content))
    except json.JSONDecodeError as exc:
        result.errors.append(f"JSON invalide : {exc.msg} (ligne {exc.lineno}).")
        return result
    records = _records_from_json(data)
    if not records:
        result.errors.append("Aucun enregistrement trouvé dans le JSON.")
        return result
    for i, rec in enumerate(records[:MAX_ROWS], start=1):
        flat = _flatten(rec)
        mapping = map_headers(list(flat.keys()), connector)
        values = {canon: flat.get(h) for h, canon in mapping.items()}
        item = build_listing(values, connector, raw=rec)
        if "marque/titre" in item.problems():
            result.skipped += 1
            result.errors.append(f"Enregistrement {i} ignoré : marque et titre absents.")
            continue
        result.listings.append(item)
    return result


# -------------------------------------------------------------------- HTML
class _HeadExtractor(HTMLParser):
    """Récupère JSON-LD, __NEXT_DATA__, balises meta et titre sans exécuter de code."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jsonld: list[str] = []
        self.next_data: str | None = None
        self.meta: dict[str, str] = {}
        self.title = ""
        self._capture: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            t = (a.get("type") or "").lower()
            if t == "application/ld+json":
                self._capture, self._buf = "ld", []
            elif a.get("id") == "__NEXT_DATA__":
                self._capture, self._buf = "next", []
        elif tag == "meta":
            key = a.get("property") or a.get("name") or a.get("itemprop")
            if key and a.get("content"):
                self.meta.setdefault(key.lower(), a["content"])
        elif tag == "title":
            self._capture, self._buf = "title", []

    def handle_endtag(self, tag):
        if tag in ("script", "title") and self._capture:
            text = "".join(self._buf)
            if self._capture == "ld":
                self.jsonld.append(text)
            elif self._capture == "next":
                self.next_data = text
            elif self._capture == "title":
                self.title = text.strip()
            self._capture = None

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)


def _iter_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dicts(v)


_VEHICLE_TYPES = {"car", "vehicle", "motorizedbicycle", "product", "offer"}


def _from_jsonld(blocks: list[str]) -> dict | None:
    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for d in _iter_dicts(data):
            types = d.get("@type")
            types = [types] if isinstance(types, str) else (types or [])
            if not {str(t).lower() for t in types} & _VEHICLE_TYPES or str(types[0]).lower() == "offer":
                continue
            offers = d.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            brand = d.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            mileage = d.get("mileageFromOdometer")
            if isinstance(mileage, dict):
                mileage = mileage.get("value")
            engine = d.get("vehicleEngine")
            fuel = d.get("fuelType")
            if isinstance(engine, dict):
                fuel = fuel or engine.get("fuelType")
                engine = engine.get("name") or engine.get("engineDisplacement")
            image = d.get("image")
            photos = image if isinstance(image, list) else ([image] if isinstance(image, str) else [])
            return {
                "title": d.get("name"),
                "make": brand or d.get("manufacturer"),
                "model": d.get("model"),
                "version": d.get("vehicleConfiguration"),
                "engine": engine if isinstance(engine, str) else None,
                "fuel": fuel,
                "gearbox": d.get("vehicleTransmission"),
                "body": d.get("bodyType"),
                "color": d.get("color"),
                "year": d.get("vehicleModelDate") or d.get("productionDate"),
                "first_registration": d.get("dateVehicleFirstRegistered"),
                "mileage_km": mileage,
                "price": (offers or {}).get("price") or d.get("price"),
                "url": d.get("url") or (offers or {}).get("url"),
                "external_id": d.get("sku") or d.get("productID") or d.get("identifier"),
                "photos": [p for p in photos if isinstance(p, str)],
            }
    return None


# Clés d'attributs du type {"key": ..., "value": ...} (format rencontré sur des
# sites d'annonces à base de Next.js, dont leboncoin à la date d'écriture).
_ATTR_KEYS = {
    "brand": "make", "u_car_brand": "make", "model": "model", "u_car_model": "model",
    "regdate": "year", "issuance_date": "first_registration", "mileage": "mileage_km",
    "fuel": "fuel", "gearbox": "gearbox", "vehicle_type": "body", "vehicule_color": "color",
    "horsepower": "fiscal_hp", "horse_power_din": "power_hp", "u_car_version": "version",
}


def _from_next_data(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    for d in _iter_dicts(data):
        attrs = d.get("attributes")
        if not (isinstance(attrs, list) and attrs and isinstance(attrs[0], dict) and "key" in attrs[0]):
            continue
        values: dict[str, Any] = {}
        for a in attrs:
            canon = _ATTR_KEYS.get(str(a.get("key")))
            if canon:
                values[canon] = a.get("value_label") if canon in {"fuel", "gearbox", "make", "model", "body", "color"} and a.get("value_label") else a.get("value")
        price = d.get("price")
        if isinstance(price, list):
            price = price[0] if price else None
        loc = d.get("location") or {}
        images = d.get("images") or {}
        values.update({
            "title": d.get("subject") or d.get("title"),
            "price": price,
            "external_id": d.get("list_id") or d.get("id"),
            "url": d.get("url"),
            "location": loc.get("city") if isinstance(loc, dict) else None,
            "postal_code": loc.get("zipcode") if isinstance(loc, dict) else None,
            "damages_text": d.get("body") if isinstance(d.get("body"), str) else None,
            "photos": images.get("urls") if isinstance(images, dict) else None,
        })
        return values
    return None


def parse_html(content: bytes, connector: "Connector", url: str | None = None) -> ParseResult:
    """Page d'annonce enregistrée depuis le navigateur (Ctrl+S)."""
    result = ParseResult()
    parser = _HeadExtractor()
    try:
        parser.feed(_decode(content))
    except Exception as exc:  # HTML très malformé
        result.errors.append(f"HTML illisible : {exc}")
        return result
    values = _from_next_data(parser.next_data) or _from_jsonld(parser.jsonld)
    source = "données structurées"
    if not values:
        meta = parser.meta
        title = meta.get("og:title") or parser.title
        price = meta.get("product:price:amount") or meta.get("og:price:amount")
        values = {"title": title, "price": price, "url": meta.get("og:url"),
                  "photos": [meta["og:image"]] if meta.get("og:image") else []}
        desc = meta.get("og:description") or meta.get("description") or ""
        if desc:
            extra = _extract_from_text(desc)
            for k, v in extra.items():
                values.setdefault(k, v)
            values["damages_text"] = desc
        source = "balises meta (extraction partielle)"
    if url:
        values["url"] = url
    item = build_listing(values, connector, raw={"source": source})
    if "marque/titre" in item.problems():
        result.errors.append("Impossible de reconnaître un véhicule dans cette page.")
        return result
    if item.price is None:
        result.errors.append("Prix introuvable dans la page : à compléter sur la fiche.")
    result.listings.append(item)
    return result


# ------------------------------------------------------------ Texte collé
def _extract_from_text(text: str) -> dict:
    t = text.replace(" ", " ").replace(" ", " ")
    values: dict[str, Any] = {}
    m = re.search(r"(\d{1,3}(?:[ .]\d{3})+|\d{4,7})\s?(?:km|kms|kilom)", t, re.I)
    if m:
        values["mileage_km"] = m.group(1)
    m = re.search(r"(\d{1,3}(?:[ .]\d{3})+|\d{3,7})\s?(?:€|eur|euros)", t, re.I)
    if m:
        values["price"] = m.group(1)
    m = re.search(r"(?:mise en circulation|mec|ann[ée]e)\s*:?\s*(\d{2}/\d{2}/\d{4}|\d{2}/\d{4}|\d{4})", t, re.I)
    if m:
        if "/" in m.group(1):
            values["first_registration"] = m.group(1)
        else:
            values["year"] = m.group(1)
    elif (y := re.search(r"\b(20[0-3]\d|19[89]\d)\b", t)):
        values["year"] = y.group(1)
    m = re.search(r"(\d{1,2})\s?cv\b", t, re.I)
    if m:
        values["fiscal_hp"] = m.group(1)
    m = re.search(r"(\d{2,3})\s?ch\b", t, re.I)
    if m:
        values["power_hp"] = m.group(1)
    fuel = normalize_fuel(t)
    if fuel:
        values["fuel"] = fuel
    gb = normalize_gearbox(t)
    if gb:
        values["gearbox"] = gb
    m = re.search(r"\b(\d{5})\b", t)
    if m:
        values["postal_code"] = m.group(1)
    if re.search(r"non[ -]roulant", t, re.I):
        values["is_running"] = False
    return values


def parse_free_text(text: str, connector: "Connector", url: str | None = None) -> ParseResult:
    """Texte copié-collé depuis une annonce : première ligne = titre."""
    result = ParseResult()
    text = (text or "").strip()
    if not text:
        result.errors.append("Texte vide.")
        return result
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    values = _extract_from_text(text)
    values["title"] = lines[0][:300]
    values["damages_text"] = "\n".join(lines[1:])[:5000] or None
    if url:
        values["url"] = url
    item = build_listing(values, connector, raw={"source": "texte collé"})
    if "marque/titre" in item.problems():
        result.errors.append("Titre introuvable.")
        return result
    result.listings.append(item)
    return result
