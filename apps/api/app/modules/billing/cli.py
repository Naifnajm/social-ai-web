"""Platform administration from the shell (on the server: inside the API container, see deploy/server/README.md).

    python -m app.modules.billing.cli set-password owner@example.com            # asks twice, never echoed
    python -m app.modules.billing.cli set-password owner@example.com --generate # strong random one, printed once
    python -m app.modules.billing.cli create-superadmin owner@example.com [--name "Naif"] [--generate]
        (a new account: asks for its password; an existing one is promoted and keeps its password)
    python -m app.modules.billing.cli revoke-superadmin other@example.com
    python -m app.modules.billing.cli list-superadmins
    python -m app.modules.billing.cli check

Passwords are typed at a hidden prompt (``getpass``) so they never reach the shell history or the logs; a password
must have at least 12 characters and must not be common or look like the e-mail address. Setting a password signs
the account out everywhere and marks the e-mail as confirmed. ``--password`` still works for scripts but warns: the
value stays in the shell history. The last active platform administrator cannot be revoked.
"""
import argparse
import getpass
import sys

from sqlalchemy import func, select

MIN_LENGTH = 12


def _session():
    from app.core import registry
    from app.core.db import SessionLocal
    registry.load_models()
    return SessionLocal()


def _find(db, email: str):
    from app.modules.auth.models import User
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def password_problem(password: str, email: str) -> str | None:
    from app.core.i18n import set_locale
    from app.modules.users.service import password_problem as problem
    set_locale("en")
    return problem(password, email=email, min_length=MIN_LENGTH)


def ask_password(email: str, attempts: int = 3) -> str | None:
    """Prompt twice at a hidden prompt until the two match and the password is strong enough."""
    for _attempt in range(attempts):
        first = getpass.getpass("New password: ")
        problem = password_problem(first, email)
        if problem:
            print(problem, file=sys.stderr)
            continue
        if getpass.getpass("Repeat the password: ") != first:
            print("The two passwords are different.", file=sys.stderr)
            continue
        return first
    return None


def _apply_password(user, password: str) -> None:
    from app.core.db import utcnow
    from app.core.security import hash_password
    user.password_hash = hash_password(password)
    user.token_version += 1           # signs out every session
    user.email_verified = True
    user.must_change_password = False
    user.password_changed_at = utcnow()


def _audit(db, user, type_: str) -> None:
    from app.modules.users.service import audit
    audit(db, user.id, type_, summary="command line")


def set_password(email: str, password: str) -> bool:
    db = _session()
    try:
        user = _find(db, email)
        if not user or user.deleted_at:
            return False
        _apply_password(user, password)
        user.is_active = True
        _audit(db, user, "cli.password_set")
        db.commit()
        return True
    finally:
        db.close()


def create_superadmin(email: str, name: str | None = None, password: str | None = None,
                      workspace: str = "Platform admin") -> tuple[bool, str | None]:
    """Return (created, generated_password). A new user also gets a workspace (the web app needs one). Without a
    password a new user gets a generated one (returned, to print once); an existing user keeps theirs."""
    from app.modules.auth.models import User
    from app.modules.users.service import generate_password
    from app.modules.workspaces.service import create_workspace

    email = email.strip().lower()
    db = _session()
    try:
        user = _find(db, email)
        generated = None
        created = user is None
        if user is None:
            generated = None if password else generate_password()
            user = User(email=email, name=name or email.split("@")[0])
            db.add(user)
            db.flush()
            _apply_password(user, password or generated)
            create_workspace(db, workspace, owner=user)
        elif password:
            _apply_password(user, password)
        if name and not created:
            user.name = name
        user.is_superadmin = True
        user.is_active = True
        _audit(db, user, "cli.superadmin_granted")
        db.commit()
        return created, generated
    finally:
        db.close()


def revoke_superadmin(email: str) -> str:
    """"ok", "missing" or "last" (the last active administrator is never revoked)."""
    from app.modules.auth.models import User
    db = _session()
    try:
        user = _find(db, email)
        if not user:
            return "missing"
        if user.is_superadmin and user.is_active and not db.scalar(
                select(func.count()).select_from(User).where(User.is_superadmin.is_(True), User.is_active.is_(True),
                                                             User.id != user.id)):
            return "last"
        user.is_superadmin = False
        user.token_version += 1
        _audit(db, user, "cli.superadmin_revoked")
        db.commit()
        return "ok"
    finally:
        db.close()


def superadmins() -> list[dict]:
    from app.modules.auth.models import User
    db = _session()
    try:
        rows = db.scalars(select(User).where(User.is_superadmin.is_(True)).order_by(User.id)).all()
        return [{"email": u.email, "name": u.name, "active": u.is_active, "last_login_at": u.last_login_at,
                 "two_factor": u.totp_enabled, "has_password": bool(u.password_hash)} for u in rows]
    finally:
        db.close()


def _print_admins(rows: list[dict]) -> None:
    for row in rows:
        login = row["last_login_at"].strftime("%Y-%m-%d %H:%M UTC") if row["last_login_at"] else "never"
        flags = [f for f, on in (("disabled", not row["active"]), ("2fa", row["two_factor"]),
                                 ("no password", not row["has_password"])) if on]
        print(f"  {row['email']:<40} last sign-in: {login}" + (f"  [{', '.join(flags)}]" if flags else ""))


def _password_from(args, email: str) -> tuple[str | None, str | None, int]:
    """(password, generated, error code) from --password / --generate / the hidden prompt."""
    if args.password is not None:
        print("Warning: a password given with --password stays in your shell history. Prefer the prompt "
              "(leave --password out) or --generate.", file=sys.stderr)
        problem = password_problem(args.password, email)
        if problem:
            print(problem, file=sys.stderr)
            return None, None, 2
        return args.password, None, 0
    if args.generate:
        from app.modules.users.service import generate_password
        value = generate_password()
        return value, value, 0
    password = ask_password(email)
    if password is None:
        print("No password set.", file=sys.stderr)
        return None, None, 2
    return password, None, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.billing.cli", description="Platform administration")
    commands = parser.add_subparsers(dest="command", required=True)
    setpw = commands.add_parser("set-password", help="set the password of an account (hidden prompt)")
    setpw.add_argument("email")
    setpw.add_argument("--generate", action="store_true", help="generate a strong password and print it once")
    setpw.add_argument("--password", help=argparse.SUPPRESS)
    create = commands.add_parser("create-superadmin", help="create or promote a platform administrator")
    create.add_argument("email")
    create.add_argument("--name")
    create.add_argument("--generate", action="store_true", help="generate a strong password and print it once")
    create.add_argument("--password", help="discouraged: it stays in the shell history")
    revoke = commands.add_parser("revoke-superadmin", help="remove platform administrator rights")
    revoke.add_argument("email")
    commands.add_parser("list-superadmins", help="list platform administrators")
    commands.add_parser("check", help="is there at least one active platform administrator?")
    args = parser.parse_args(argv)

    if args.command in ("set-password", "create-superadmin") and "@" not in args.email:
        print("Invalid e-mail address.", file=sys.stderr)
        return 2

    if args.command == "set-password":
        db = _session()
        try:
            exists = _find(db, args.email) is not None
        finally:
            db.close()
        if not exists:
            print("No user with this e-mail.", file=sys.stderr)
            return 1
        password, generated, error = _password_from(args, args.email)
        if error:
            return error
        set_password(args.email, password)
        print(f"Password set for {args.email.strip().lower()}. Every session was signed out.")
        if generated:
            print(f"New password (shown once, store it in a password manager): {generated}")
        return 0

    if args.command == "create-superadmin":
        db = _session()
        try:
            exists = _find(db, args.email) is not None
        finally:
            db.close()
        password = generated = None
        # an existing account keeps its password unless one is given; a new account always gets one
        if not exists or args.password is not None or args.generate:
            password, generated, error = _password_from(args, args.email)
            if error:
                return error
        created, auto = create_superadmin(args.email, args.name, password)
        print(f"{'Created' if created else 'Promoted'} superadmin {args.email.strip().lower()}")
        if generated or auto:
            print(f"Password (shown once, store it in a password manager): {generated or auto}")
        return 0

    if args.command == "revoke-superadmin":
        result = revoke_superadmin(args.email)
        if result == "missing":
            print("No user with this e-mail.", file=sys.stderr)
            return 1
        if result == "last":
            print("Refused: this is the last active platform administrator. Create another one first.",
                  file=sys.stderr)
            return 3
        print(f"Revoked superadmin {args.email.strip().lower()}")
        return 0

    rows = superadmins()
    if args.command == "list-superadmins":
        if not rows:
            print("No platform administrators.")
        else:
            print(f"{len(rows)} platform administrator(s):")
            _print_admins(rows)
        return 0
    if args.command == "check":
        active = [r for r in rows if r["active"]]
        if not active:
            print("NOT OK: no active platform administrator. Run create-superadmin.")
            return 1
        print(f"OK: {len(active)} active platform administrator(s).")
        _print_admins(active)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
