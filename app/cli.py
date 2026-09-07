"""Trusted operator CLI. Never expose this command through an HTTP endpoint."""

import argparse
import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import update

from app.db import SessionLocal
from app.models import AccessToken, User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user")
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=["CUSTOMER", "AGENT", "ADMIN"], required=True)
    issue = commands.add_parser("issue-token")
    issue.add_argument("--user", type=UUID, required=True)
    issue.add_argument("--output", type=Path, required=True, help="New private .token file")
    issue.add_argument("--hours", type=int, choices=range(1, 25), default=8)
    revoke = commands.add_parser("revoke-tokens")
    revoke.add_argument("--user", type=UUID, required=True)
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        if args.command == "create-user":
            name = args.name.strip()
            if not 1 <= len(name) <= 100:
                parser.error("Name must have 1-100 characters")
            user = User(name=name, role=args.role)
            db.add(user)
            db.flush()
            print(f"User ID: {user.id}")
        elif args.command == "issue-token":
            user = db.get(User, args.user)
            if user is None or not user.active:
                parser.error("Active user not found")
            if args.output.suffix != ".token":
                parser.error("Use a .token file in a private directory")
            secret = secrets.token_urlsafe(32)
            digest = hashlib.sha256(secret.encode()).hexdigest()
            db.add(
                AccessToken(
                    digest=digest,
                    user_id=user.id,
                    expires_at=datetime.now(UTC) + timedelta(hours=args.hours),
                )
            )
            db.flush()
            # Exclusive creation prevents overwriting files or following existing symlinks.
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(secret)
            print("Token written to the requested file. Protect its directory ACL on Windows.")
        else:
            db.execute(
                update(AccessToken).where(AccessToken.user_id == args.user).values(revoked=True)
            )
            print("All tokens revoked for the requested user.")


if __name__ == "__main__":
    main()
