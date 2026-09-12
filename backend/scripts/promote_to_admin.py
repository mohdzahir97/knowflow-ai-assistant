"""Grant or revoke the administrator role for an existing account.

Why this is a script and not an endpoint
----------------------------------------
There is deliberately no API that lets an account change its own role - that
would defeat the entire control, since anyone who can register could then
manage the shared knowledge base. Role changes therefore require access to
the server, which is exactly the trust boundary intended.

This is also how the *first* administrator is created. Every account starts
as USER, and only an ADMIN can upload documents, so without this step a
fresh installation has no way to populate its knowledge base.

Usage
-----
    python scripts/promote_to_admin.py someone@example.com
    python scripts/promote_to_admin.py someone@example.com --revoke
    python scripts/promote_to_admin.py --list
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a plain script from the backend directory, matching how
# the other scripts here are invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models.audit import AuditAction  # noqa: E402
from app.db.models.user import User, UserRole  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.audit_service import get_audit_service  # noqa: E402


def _list_users() -> int:
    with SessionLocal() as db:
        users = db.query(User).order_by(User.created_at).all()
        if not users:
            print("No accounts exist yet. Register one through the app first.")
            return 0
        width = max(len(user.email) for user in users)
        for user in users:
            status = "" if user.is_active else "  (inactive)"
            print(f"{user.email:<{width}}  {user.role.value}{status}")
    return 0


def _set_role(email: str, role: UserRole) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is None:
            print(f"No account found for {email!r}. Register it through the app first.", file=sys.stderr)
            return 1

        if user.role is role:
            print(f"{email} is already {role.value}. Nothing to do.")
            return 0

        # Refuse to remove the last administrator: doing so would leave the
        # knowledge base unmanageable, recoverable only by editing the
        # database by hand.
        if role is UserRole.USER:
            remaining = db.query(User).filter(User.role == UserRole.ADMIN, User.id != user.id).count()
            if remaining == 0:
                print(
                    f"Refusing to revoke: {email} is the only administrator, "
                    "and no one else could manage the knowledge base.",
                    file=sys.stderr,
                )
                return 1

        previous = user.role.value
        user.role = role
        db.commit()

        # A privilege change is exactly what an audit trail is for. Recorded
        # as an operator action since it happens on the server, not via the API.
        get_audit_service().record(
            db,
            AuditAction.ROLE_CHANGED,
            user=user,
            resource_type="user",
            resource_id=user.id,
            detail={"from": previous, "to": role.value, "via": "promote_to_admin script"},
        )
        print(f"{email}: {previous} -> {role.value}")

    print("The change takes effect on their next request; a signed-in user should sign out and back in.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Grant or revoke the administrator role.")
    parser.add_argument("email", nargs="?", help="Email address of an existing account.")
    parser.add_argument("--revoke", action="store_true", help="Demote to an ordinary user instead.")
    parser.add_argument("--list", action="store_true", help="List every account and its role, then exit.")
    args = parser.parse_args()

    if args.list:
        return _list_users()
    if not args.email:
        parser.error("an email address is required (or pass --list)")

    return _set_role(args.email, UserRole.USER if args.revoke else UserRole.ADMIN)


if __name__ == "__main__":
    raise SystemExit(main())
