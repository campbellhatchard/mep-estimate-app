from fastapi import Request, HTTPException
from argon2 import PasswordHasher
from sqlalchemy.orm import Session
from .models import User

ph = PasswordHasher()

def normalize_username(username: str) -> str:
    return username.strip().casefold()

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except Exception:
        return False

def authenticate(db: Session, username: str, password: str):
    user = db.query(User).filter(User.username_normalized == normalize_username(username), User.active.is_(True)).first()
    if user and verify_password(password, user.password_hash):
        return user
    return None

def current_user(request: Request, db: Session) -> User:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = db.get(User, uid)
    if not user or not user.active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

def require_role(user: User, *roles: str):
    if not user.has_role(*roles):
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
