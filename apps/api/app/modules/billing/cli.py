"""Platform administration from the shell.

    uv run python -m app.modules.billing.cli create-superadmin owner@example.com [--name "Naif"] [--password ...]
    uv run python -m app.modules.billing.cli revoke-superadmin owner@example.com

``create-superadmin`` promotes an existing user, or creates the user (with a random password printed once
when ``--password`` is not given). Superadmins see the platform admin at /<locale>/admin.
"""
import argparse
import secrets
import sys

from sqlalchemy import func, select


def _session():
    from app.core import registry
    from app.core.db import SessionLocal
    registry.load_models()
    return SessionLocal()


def create_superadmin(email: str, name: str | None = None, password: str | None = None,
                      workspace: str = "Platform admin") -> tuple[bool, str | None]:
    """Return (created, generated_password). A new user also gets a workspace (the web app needs one)."""
    from app.core.security import hash_password
    from app.modules.auth.models import User
    from app.modules.workspaces.service import create_workspace

    email = email.strip().lower()
    db = _session()
    try:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        generated = None
        created = user is None
        if user is None:
            generated = None if password else secrets.token_urlsafe(12)
            user = User(email=email, name=name or email.split("@")[0], password_hash=hash_password(password or generated),
                        email_verified=True)
            db.add(user)
            db.flush()
            create_workspace(db, workspace, owner=user)
        elif password:
            user.password_hash = hash_password(password)
            user.token_version += 1
        user.is_superadmin = True
        user.is_active = True
        db.commit()
        return created, generated
    finally:
        db.close()


def revoke_superadmin(email: str) -> bool:
    from app.modules.auth.models import User
    db = _session()
    try:
        user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
        if not user:
            return False
        user.is_superadmin = False
        user.token_version += 1
        db.commit()
        return True
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.billing.cli", description="Platform administration")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-superadmin", help="create or promote a platform administrator")
    create.add_argument("email")
    create.add_argument("--name")
    create.add_argument("--password")
    revoke = commands.add_parser("revoke-superadmin", help="remove platform administrator rights")
    revoke.add_argument("email")
    args = parser.parse_args(argv)

    if args.command == "create-superadmin":
        if "@" not in args.email:
            print("Invalid e-mail address.", file=sys.stderr)
            return 2
        if args.password is not None and len(args.password) < 8:
            print("The password must have at least 8 characters.", file=sys.stderr)
            return 2
        created, generated = create_superadmin(args.email, args.name, args.password)
        print(f"{'Created' if created else 'Promoted'} superadmin {args.email.lower()}")
        if generated:
            print(f"Temporary password (shown once): {generated}")
        return 0
    if args.command == "revoke-superadmin":
        if not revoke_superadmin(args.email):
            print("No user with this e-mail.", file=sys.stderr)
            return 1
        print(f"Revoked superadmin {args.email.lower()}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
