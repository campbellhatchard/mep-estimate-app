from __future__ import annotations

from dataclasses import dataclass

from app.auth import hash_password, normalize_username
from app.database import SessionLocal
from app.models import User, UserRole


DEFAULT_PASSWORD = "E2E-TestPass-2026!"


@dataclass(frozen=True)
class SyntheticUser:
    username: str
    roles: tuple[str, ...]
    active: bool = True
    password: str = DEFAULT_PASSWORD


USERS = {
    "admin": SyntheticUser("E2EAdmin", ("ADMIN",)),
    "tools": SyntheticUser("E2EToolsAdmin", ("TOOLS_ADMIN",)),
    "estimator": SyntheticUser("E2EEstimator", ("ESTIMATOR",)),
    "reviewer": SyntheticUser("E2EReviewer", ("REVIEWER",)),
    "approver": SyntheticUser("E2EApprover", ("APPROVER",)),
    "sow_approver": SyntheticUser("E2ESowApprover", ("SOW_APPROVER",)),
    "readonly": SyntheticUser("E2EReadOnly", ("READ_ONLY",)),
    "multi": SyntheticUser("E2EMultiRole", ("ESTIMATOR", "APPROVER")),
    "inactive": SyntheticUser("E2EInactive", ("ESTIMATOR",), active=False),
}


def _apply_roles(user: User, roles: tuple[str, ...]) -> None:
    existing = {row.role: row for row in user.roles if row.role}
    desired = set(roles)
    for role, row in list(existing.items()):
        if role not in desired:
            user.roles.remove(row)
    for role in roles:
        if role not in existing:
            user.roles.append(UserRole(role=role))
    user.role = roles[0] if roles else "READ_ONLY"


def ensure_e2e_users() -> None:
    with SessionLocal() as db:
        for spec in USERS.values():
            normalized = normalize_username(spec.username)
            user = db.query(User).filter(User.username_normalized == normalized).first()
            if not user:
                user = User(
                    username=spec.username,
                    username_normalized=normalized,
                    password_hash=hash_password(spec.password),
                    role=spec.roles[0],
                    email=f"{normalized}@example.test",
                    active=spec.active,
                )
                db.add(user)
                db.flush()
            else:
                user.username = spec.username
                user.password_hash = hash_password(spec.password)
                user.email = f"{normalized}@example.test"
                user.active = spec.active
            _apply_roles(user, spec.roles)
        db.commit()


if __name__ == "__main__":
    ensure_e2e_users()
    print(f"Seeded {len(USERS)} synthetic E2E users.")
