"""Un connecteur indépendant par plateforme.

Statuts vérifiés le 12/11/2026 depuis le serveur de développement :
- VPauto : robots.txt interdit /vehicle/list aux robots.
- Enchères Domaine : page protégée par un test anti-robot JavaScript.
- Alcopa Auction : requête automatisée refusée (HTTP 405).
- Leboncoin / La Centrale : pas d'API publique d'annonces ; extraction de leur base
  encadrée (droit sui generis des bases de données, cf. Cass. 1re civ. 15/10/2025
  n° 23-23.167 concernant La Centrale).
- BCA : plateforme réservée aux professionnels inscrits, sans API publique.
Aucun de ces sites n'est donc interrogé automatiquement : chaque connecteur propose
l'import manuel, et la synchronisation automatique via un flux fourni par la
plateforme (export, API partenaire) dès qu'un accès autorisé est configuré.
"""
from __future__ import annotations

from .base import Connector, ConnectorStatus, PlatformFees

_FEES_NOTE = "Valeur indicative à vérifier dans les conditions de vente de chaque vacation."


class AlcopaConnector(Connector):
    key = "alcopa"
    name = "Alcopa Auction"
    website = "https://www.alcopa-auction.fr"
    kind = "enchere"
    status = ConnectorStatus.AUTORISATION
    status_reason = (
        "Pas d'API publique. Les requêtes automatisées sont refusées par le site "
        "(test du 12/11/2026). Une récupération automatique nécessite un accord d'Alcopa."
    )
    how_to_authorize = (
        "Demander à Alcopa Auction (service client professionnels) un export ou un accès API "
        "à votre catalogue, puis renseigner l'URL du flux dans ce connecteur."
    )
    how_to_export = (
        "Enregistrez la page d'un lot (Ctrl+S) et importez le fichier .html, ou copiez-collez "
        "le descriptif du lot, ou importez un CSV (modèle téléchargeable)."
    )
    default_price_type = "enchere_depart"
    default_seller_type = "enchere"
    default_fees = PlatformFees(pct=0.14, fixed=0, note=_FEES_NOTE)
    extra_aliases = {"price": ["prix de depart", "estimation"], "damages_text": ["frais de remise en etat estimes", "bilan expert"]}


class VPautoConnector(Connector):
    key = "vpauto"
    name = "VPauto"
    website = "https://www.vpauto.fr"
    kind = "enchere"
    status = ConnectorStatus.AUTORISATION
    status_reason = (
        "Le fichier robots.txt de VPauto interdit l'accès automatisé aux listes de véhicules "
        "(Disallow: /vehicle/list). Pas d'API publique."
    )
    how_to_authorize = (
        "Votre conseiller VPauto (compte pro) peut fournir un export de catalogue ; "
        "renseignez ensuite l'URL du flux dans ce connecteur."
    )
    how_to_export = (
        "Enregistrez la fiche véhicule (Ctrl+S) et importez le .html, collez le texte de la fiche "
        "et du bilan expert, ou importez un CSV."
    )
    default_price_type = "enchere_depart"
    default_seller_type = "enchere"
    default_fees = PlatformFees(pct=0.12, fixed=150, note=_FEES_NOTE + " Les CGV pro mentionnent des frais fixes de 125 € HT par véhicule thermique.")
    extra_aliases = {"damages_text": ["bilan expert", "frais de remise en etat"]}


class DomaineConnector(Connector):
    key = "domaine"
    name = "Enchères Domaine"
    website = "https://www.encheres-domaine.gouv.fr"
    kind = "enchere"
    status = ConnectorStatus.MANUEL
    status_reason = (
        "Site public de l'État, mais protégé par un test anti-robot JavaScript (vérifié le 12/11/2026) "
        "et sans API publique : import manuel."
    )
    how_to_authorize = (
        "Le service des ventes du Domaine (DNID) peut être sollicité pour un export ; à défaut, "
        "l'import manuel reste la seule voie."
    )
    how_to_export = "Enregistrez la page du lot (Ctrl+S) puis importez-la, ou collez le descriptif."
    default_price_type = "enchere_depart"
    default_seller_type = "enchere"
    default_fees = PlatformFees(pct=0.11, fixed=0, note="11 % selon le dépliant officiel du Domaine (2022). " + _FEES_NOTE)
    extra_aliases = {"price": ["mise a prix"]}


class BCAConnector(Connector):
    key = "bca"
    name = "BCA (BCAuto Enchères)"
    website = "https://www.bca.fr"
    kind = "enchere"
    status = ConnectorStatus.AUTORISATION
    status_reason = "Plateforme réservée aux professionnels inscrits (SIRET, Kbis), sans API publique."
    how_to_authorize = (
        "Avec un compte professionnel BCA, demander à votre interlocuteur un export de catalogue "
        "ou un accès partenaire, puis le configurer ici."
    )
    how_to_export = "Exportez ou recopiez la liste des lots dans le modèle CSV, ou enregistrez les fiches en .html."
    default_price_type = "enchere_depart"
    default_seller_type = "enchere"
    default_fees = PlatformFees(pct=0.05, fixed=100, note="Commission B2B usuelle 3 à 8 % + frais de dossier. " + _FEES_NOTE)


class LeboncoinConnector(Connector):
    key = "leboncoin"
    name = "Leboncoin"
    website = "https://www.leboncoin.fr"
    kind = "annonce"
    status = ConnectorStatus.MANUEL
    status_reason = (
        "Pas d'API publique de consultation des annonces ; le site est protégé contre l'extraction "
        "automatisée. Import manuel uniquement."
    )
    how_to_authorize = "Aucune voie d'accès automatique ouverte aux particuliers à ce jour."
    how_to_export = (
        "Ouvrez l'annonce, enregistrez la page (Ctrl+S, « page web complète ») et importez le .html : "
        "les données structurées de la page sont lues. Ou copiez-collez le texte de l'annonce."
    )
    default_price_type = "prix_fixe"
    is_retail_reference = True
    default_fees = PlatformFees(pct=0.0, fixed=0, note="Achat entre particuliers : pas de frais de plateforme.")


class LaCentraleConnector(Connector):
    key = "lacentrale"
    name = "La Centrale"
    website = "https://www.lacentrale.fr"
    kind = "annonce"
    status = ConnectorStatus.MANUEL
    status_reason = (
        "Pas d'API publique. La Centrale protège sa base d'annonces (droit des bases de données, "
        "Cass. 1re civ. 15/10/2025). Import manuel uniquement."
    )
    how_to_authorize = "Aucune voie d'accès automatique ouverte aux particuliers à ce jour."
    how_to_export = "Enregistrez l'annonce (Ctrl+S) et importez le .html, ou copiez-collez le texte."
    default_price_type = "prix_fixe"
    is_retail_reference = True
    default_fees = PlatformFees(pct=0.0, fixed=0, note="Achat auprès d'un particulier ou d'un pro : pas de frais de plateforme.")


class ManualConnector(Connector):
    key = "manuel"
    name = "Saisie manuelle / autre source"
    website = ""
    kind = "annonce"
    status = ConnectorStatus.MANUEL
    status_reason = "Véhicules saisis à la main ou provenant d'une autre source."
    how_to_export = "Formulaire « Ajouter un véhicule » ou import CSV."
    default_fees = PlatformFees(pct=0.0, fixed=0)
