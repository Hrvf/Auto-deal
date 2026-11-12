# AutoDeal Comparator

Comparateur automobile privé : il centralise les lots d'enchères (Alcopa Auction, VPauto, Enchères Domaine, BCA) et les annonces du marché (Leboncoin, La Centrale), puis analyse chaque véhicule. L'analyse couvre la fiabilité mécanique, les réparations, le prix de revente, les frais, la marge et une note sur 100.

## Fonctionnalités

| Domaine | Ce qui est en place |
|---|---|
| Connecteurs | Un connecteur indépendant par plateforme, avec un statut honnête (voir plus bas) |
| Imports | CSV/TSV (en-têtes français reconnus, encodages UTF-8 et Windows), JSON, page d'annonce enregistrée (.html : JSON-LD schema.org, `__NEXT_DATA__`, balises meta), texte copié-collé |
| Récupération automatique | Synchronisation d'un **flux autorisé** (export ou API fourni par la plateforme), en HTTPS, avec en-tête d'authentification. Planifiable : `python -m app.cli synchroniser` |
| Base de données | Centralisée (SQLite par défaut, PostgreSQL en production), dédoublonnage par plateforme + référence. Les réimports mettent à jour les annonces sans écraser vos notes, favoris ni statuts |
| Analyse | Fiabilité (base de défauts connus : PureTech, THP, TSI EA111, DSG7, TCe 1.2, EcoBoost, Powershift, N47…), réparations à partir des défauts déclarés (avec gestion des négations : « pneus neufs »), revente par comparables ajustés âge/km, frais acheteur, carte grise, TVA sur marge, enchère maximale conseillée |
| Note /100 | Rentabilité 40 · Fiabilité 25 · État 20 · Facilité de revente 10 · Qualité des données 5, avec le détail affiché |
| Interface | En français, responsive : tableau de bord, liste filtrable (plateformes, marque, prix, km, note, marge, département…), filtres enregistrés, fiche détaillée, export CSV, paramètres |
| Sécurité | Site privé (connexion obligatoire), mots de passe scrypt, CSRF sur tous les formulaires, limitation des tentatives de connexion, CSP stricte, cookies HttpOnly/SameSite (Secure en HTTPS), rôles admin/membre |
| API | `GET /api/annonces` et `GET /api/annonces/{id}` (JSON, authentifiée) : base de la future version publique |

## Statut réel des connecteurs (vérifié le 12/11/2026)

| Plateforme | Statut | Raison |
|---|---|---|
| Alcopa Auction | Autorisation requise | Pas d'API publique ; requêtes automatisées refusées (HTTP 405) |
| VPauto | Autorisation requise | `robots.txt` interdit `/vehicle/list` aux robots |
| BCA | Autorisation requise | Réservé aux pros inscrits, pas d'API publique |
| Enchères Domaine | Import manuel | Site public mais protégé par un test anti-robot JavaScript |
| Leboncoin | Import manuel | Pas d'API publique, protection anti-extraction |
| La Centrale | Import manuel | Pas d'API publique ; base protégée (Cass. 1re civ. 15/10/2025, n° 23-23.167) |

**Aucun site n'est aspiré.** Un connecteur passe en « Automatique » dès qu'un administrateur configure un flux fourni par la plateforme et indique l'autorisation obtenue.

## Extension Chrome « AutoDeal Capture » (Alcopa, Leboncoin…)

Sur une annonce Leboncoin ou un lot Alcopa que vous consultez, un clic sur l'icône AutoDeal envoie la page au site, qui l'analyse et affiche la note, la marge et l'enchère maximale. L'extension ne lit que la page affichée, uniquement après votre clic (permission `activeTab`), et n'a aucun accès permanent aux sites.

1. Paramètres → Extension navigateur → télécharger `autodeal-capture.zip`, décompresser.
2. `chrome://extensions` → Mode développeur → « Charger l'extension non empaquetée ».
3. Créer un jeton dans Paramètres, puis le coller avec l'adresse du site dans les réglages de l'extension.

Côté serveur : `POST /api/capture` n'accepte qu'un jeton personnel (jamais le cookie de session), stocké sous forme d'empreinte SHA-256 et révocable. Les requêtes cross-origin ne sont acceptées que depuis une extension.

## Démarrage local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.cli demo            # facultatif : données FICTIVES (références DEMO-)
uvicorn app.main:app --reload
```

Ouvrez http://localhost:8000. À la première visite, la page d'installation crée le compte administrateur.
Pour retirer les données de démo : `python -m app.cli purger-demo`.

## Tests

```bash
pytest
```

42 tests couvrent la normalisation, chaque format d'import, l'analyse (fiabilité, réparations, frais, enchère max, note), le parcours web complet et la sécurité (CSRF, limitation de connexion, redirections, droits). Ils couvrent aussi la synchronisation d'un flux autorisé (simulée) et la capture par l'extension (jeton, CORS, pages avec ou sans données structurées).

## Mise en ligne

1. Copier `.env.example` en `.env` et définir `SECRET_KEY`, `DATABASE_URL`, `SETUP_TOKEN`, `HTTPS_ONLY=true`.
2. `docker compose up -d --build`
3. Placer un proxy HTTPS (Caddy, Nginx, ou l'hébergeur) devant le port 8000.
4. Créer l'admin : via `/installation` avec le `SETUP_TOKEN`, ou `docker compose exec web python -m app.cli creer-admin --email vous@exemple.fr`.
5. Facultatif : planifier `python -m app.cli synchroniser` (cron) pour les flux autorisés.

## Limites connues

- Les frais acheteur par défaut sont **indicatifs** : ajustez-les dans Paramètres selon les conditions de chaque vente.
- La base de fiabilité signale des risques documentés : elle ne remplace ni l'historique d'entretien ni une inspection.
- L'estimation de revente dépend des annonces comparables importées : plus vous importez d'annonces du marché, plus elle est fiable. Sinon, saisissez une cote sur la fiche.
- Le schéma est créé automatiquement au démarrage. Pour des évolutions de schéma en production, ajouter Alembic.

## Structure

```
app/
  connectors/   base, normalisation, parseurs, un connecteur par plateforme
  analysis/     fiabilité, réparations, prix de revente, coûts, note, orchestration
  routes/       auth, annonces, imports/connecteurs, paramètres, API
  templates/    pages Jinja (français)
  static/       CSS, JS (aucun script en ligne)
  services.py   imports, dédoublonnage, synchronisation des flux
  cli.py        creer-admin, analyser, synchroniser, demo, purger-demo
tests/          tests + jeux de données fictifs (scripts/generate_demo_data.py)
```
