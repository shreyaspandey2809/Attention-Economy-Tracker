"""Operator CLI (there is deliberately no public sign-up endpoint).

    python -m attention_tracker.api.admin create-device <user_id>
    python -m attention_tracker.api.admin revoke-device <device_id>
    python -m attention_tracker.api.admin list-users
    python -m attention_tracker.api.admin score [--user <user_id>]
    python -m attention_tracker.api.admin delete-user <user_id> --yes

The DB is --db, else $ATTENTION_DB_PATH, else ./attention.db.
"""

import argparse
import os
import sys

from attention_tracker.api.app import DB_ENV_VAR, DEFAULT_DB_PATH
from attention_tracker.api.auth import issue_device
from attention_tracker.api.scoring_job import ModelCache, ScoringJob
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.storage.db import Database
from attention_tracker.storage.repository import Repository


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="attention_tracker.api.admin", description=__doc__.split("\n")[0])
    p.add_argument("--db", default=None, help="SQLite path")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create-device", help="register a device for a user and print its token once")
    c.add_argument("user_id")
    r = sub.add_parser("revoke-device", help="disable a device token")
    r.add_argument("device_id")
    sub.add_parser("list-users", help="list users, consent and staleness")
    s = sub.add_parser("score", help="run the scoring job now")
    s.add_argument("--user", default=None, help="one user; default = every stale user")
    d = sub.add_parser("delete-user", help="hard-delete a user and all their data")
    d.add_argument("user_id")
    d.add_argument("--yes", action="store_true", help="required; confirms irreversible deletion")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = Database(args.db or os.environ.get(DB_ENV_VAR, DEFAULT_DB_PATH))
    repo = Repository(db)

    if args.cmd == "create-device":
        device_id, token = issue_device(repo, args.user_id)
        print(f"user_id:   {args.user_id}")
        print(f"device_id: {device_id}")
        print(f"token:     {token}")
        print("Store the token now; it cannot be shown again.", file=sys.stderr)
        return 0

    if args.cmd == "revoke-device":
        if not repo.revoke_device(args.device_id):
            print("no active device with that id", file=sys.stderr)
            return 1
        print("revoked")
        return 0

    if args.cmd == "list-users":
        for uid in repo.list_user_ids():
            u = repo.get_user(uid)
            print(f"{uid}\tconsent={'yes' if u['consent_at'] else 'no'}\tstale={bool(u['scores_stale'])}")
        return 0

    if args.cmd == "score":
        job = ScoringJob(repo, TaxonomyLoader(include_extended=True), ModelCache())
        if args.user:
            if repo.get_user(args.user) is None:
                print("no such user", file=sys.stderr)
                return 1
            summaries = [job.score_user(args.user)]
        else:
            summaries = job.score_stale_users()
        for s in summaries:
            print(f"{s.user_id}: {s.sessions} sessions, {s.windows} windows, {s.days} days")
        return 0

    if args.cmd == "delete-user":
        if not args.yes:
            print("refusing without --yes", file=sys.stderr)
            return 2
        if not repo.delete_user(args.user_id):
            print("no such user", file=sys.stderr)
            return 1
        print("deleted")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
