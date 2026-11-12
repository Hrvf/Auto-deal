"""Commandes d'administration.

    python -m app.cli creer-admin --email vous@exemple.fr
    python -m app.cli analyser          # réanalyse toutes les annonces
    python -m app.cli synchroniser      # synchronise les flux autorisés (à planifier en cron)
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select

from .analysis.engine import analyze_all
from .db import SessionLocal, init_db
from .models import ConnectorConfig, User
from .security import hash_password
from .services import FeedError, sync_feed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("creer-admin", help="Créer un compte administrateur")
    p.add_argument("--email", required=True)
    p.add_argument("--nom", default="")
    sub.add_parser("analyser", help="Réanalyser toutes les annonces")
    sub.add_parser("synchroniser", help="Synchroniser les flux autorisés activés")
    sub.add_parser("demo", help="Charger des données FICTIVES de démonstration (références DEMO-)")
    sub.add_parser("purger-demo", help="Supprimer les données de démonstration")
    args = parser.parse_args(argv)

    init_db()
    with SessionLocal() as db:
        if args.cmd == "creer-admin":
            email = args.email.strip().lower()
            if db.scalar(select(User).where(func.lower(User.email) == email)):
                print("Ce compte existe déjà.", file=sys.stderr)
                return 1
            pwd = getpass.getpass("Mot de passe (10 caractères min.) : ")
            if pwd != getpass.getpass("Confirmation : "):
                print("Les mots de passe ne correspondent pas.", file=sys.stderr)
                return 1
            try:
                db.add(User(email=email, display_name=args.nom, password_hash=hash_password(pwd), role="admin"))
            except ValueError as exc:
                print(exc, file=sys.stderr)
                return 1
            db.commit()
            print(f"Administrateur {email} créé.")
        elif args.cmd == "analyser":
            n = analyze_all(db)
            db.commit()
            print(f"{n} annonce(s) analysée(s).")
        elif args.cmd == "synchroniser":
            configs = db.scalars(select(ConnectorConfig).where(ConnectorConfig.feed_enabled.is_(True))).all()
            if not configs:
                print("Aucun flux autorisé activé.")
            code = 0
            for cfg in configs:
                try:
                    job = sync_feed(db, cfg.platform)
                    print(f"{cfg.platform} : {job.created_count} créées, {job.updated_count} mises à jour.")
                except FeedError as exc:
                    print(f"{cfg.platform} : échec — {exc}", file=sys.stderr)
                    code = 2
            return code
        elif args.cmd == "demo":
            from pathlib import Path

            from .services import import_file
            fx = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
            for platform, name in (("leboncoin", "leboncoin_comparables.csv"), ("alcopa", "alcopa_lots.csv"),
                                   ("bca", "flux_bca.json"), ("lacentrale", "page_jsonld.html")):
                job = import_file(db, platform, name, (fx / name).read_bytes())
                print(f"{platform} : {job.created_count} ajoutée(s), {job.updated_count} mise(s) à jour")
            print("Données fictives chargées (références DEMO-). Supprimez-les avec : python -m app.cli purger-demo")
        elif args.cmd == "purger-demo":
            from .models import Listing
            rows = db.scalars(select(Listing).where(Listing.external_id.like("DEMO-%"))).all()
            for r in rows:
                db.delete(r)
            db.flush()
            analyze_all(db)
            db.commit()
            print(f"{len(rows)} annonce(s) de démonstration supprimée(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
