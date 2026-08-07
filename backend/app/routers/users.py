import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import ADMIN_KEY
from ..db import get_db
from ..models import User
from ..schemas import IdentifyRequest, UserCreate, UserInfo

router = APIRouter(prefix="/api/users", tags=["users"])

ROLE_LABELS = {
    "SE": "System Engineer",
    "TPM": "TPM",
    "DEV": "Developer",
}

NO_KEY_CONFIGURED = (
    "Group management is locked because no admin passphrase is set. "
    "Add ADMIN_KEY=... to backlog_manager/backend/.env and restart the API."
)


def require_admin(x_admin_key: str = Header(default="")):
    """Guard group changes with the shared passphrase from the backend .env."""
    if not ADMIN_KEY:
        raise HTTPException(status_code=503, detail=NO_KEY_CONFIGURED)
    if not hmac.compare_digest(x_admin_key.strip(), ADMIN_KEY):
        raise HTTPException(status_code=403, detail="Wrong admin passphrase.")


@router.get("/admin", response_model=dict)
def admin_state(x_admin_key: str = Header(default="")):
    """Lets the UI show whether group editing is unlocked, and validate a passphrase."""
    return {
        "configured": bool(ADMIN_KEY),
        "unlocked": bool(ADMIN_KEY) and hmac.compare_digest(x_admin_key.strip(), ADMIN_KEY),
    }


@router.get("", response_model=list[UserInfo])
def list_users(db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.role, User.email))
    return [UserInfo.model_validate(u, from_attributes=True) for u in users]


@router.post("", response_model=UserInfo, dependencies=[Depends(require_admin)])
def add_user(body: UserCreate, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if body.role not in ROLE_LABELS:
        raise HTTPException(
            status_code=400, detail=f"role must be one of {', '.join(ROLE_LABELS)}"
        )
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        existing.name = body.name.strip() or existing.name
        existing.role = body.role
        db.commit()
        return UserInfo.model_validate(existing, from_attributes=True)

    user = User(email=email, name=body.name.strip(), role=body.role)
    db.add(user)
    db.commit()
    return UserInfo.model_validate(user, from_attributes=True)


@router.delete("/{user_id}", dependencies=[Depends(require_admin)])
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    db.delete(user)
    db.commit()
    return {"deleted": user_id}


@router.post("/identify", response_model=UserInfo)
def identify(body: IdentifyRequest, db: Session = Depends(get_db)):
    """Resolve a typed name or TD SYNNEX email to a group member."""
    value = body.identifier.strip().lower()
    if not value:
        raise HTTPException(status_code=400, detail="Please enter your name or email address")

    user = db.scalar(select(User).where(func.lower(User.email) == value))
    if user is None:
        matches = list(db.scalars(select(User).where(func.lower(User.name) == value)))
        if len(matches) > 1:
            raise HTTPException(
                status_code=409,
                detail=f"'{body.identifier}' matches {len(matches)} people. Enter your email address instead.",
            )
        user = matches[0] if matches else None

    if user is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{body.identifier}' is not in the System Engineer, TPM, or Developer "
                "groups. Ask an admin to add you on the Users page."
            ),
        )
    return UserInfo.model_validate(user, from_attributes=True)
