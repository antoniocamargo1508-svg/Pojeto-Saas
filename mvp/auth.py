import binascii
import hashlib
import hmac
import os
import secrets
import sys
import traceback
from datetime import datetime, timedelta
from sqlalchemy import false
from sqlalchemy import select
from mvp.database import SessionLocal
from mvp.models import PasswordResetToken, Tenant, TenantInvite, User

DEBUG_MODE = os.getenv("DEBUG_MODE", "").strip() == "1"

def _log(msg: str, error: Exception | None = None) -> None:
    """Log messages with optional exception details."""
    if DEBUG_MODE or error:
        timestamp = datetime.utcnow().isoformat()
        prefix = f"[{timestamp}] AUTH:"
        print(f"{prefix} {msg}", file=sys.stderr)
        if error and DEBUG_MODE:
            print(f"{prefix} ERROR: {type(error).__name__}: {str(error)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
from mvp.database import SessionLocal
from mvp.models import PasswordResetToken, Tenant, TenantInvite, User

DEBUG_MODE = os.getenv("DEBUG_MODE", "").strip() == "1"

def _log(msg: str, error: Exception | None = None) -> None:
    """Log messages with optional exception details."""
    if DEBUG_MODE or error:
        timestamp = datetime.utcnow().isoformat()
        prefix = f"[{timestamp}] AUTH:"
        print(f"{prefix} {msg}", file=sys.stderr)
        if error and DEBUG_MODE:
            print(f"{prefix} ERROR: {type(error).__name__}: {str(error)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)


def 
    try:
        with SessionLocal() as db:
            _log(f"Creating tenant for {email}...")
            tenant = Tenant(name=tenant_name, plan="starter", trial_ends_at=trial_ends_at)
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
            _log(f"Tenant created: id={tenant.id}, name={tenant.name}")
            return tenant
    except Exception as e:
        _log(f"Failed to create tenant for {email}", e)
        raise
        return "Minha Empresa"
    base = domain.split(".", 1)[0]
    return (base or "Minha Empresa").title()


def _get_or_create_tenant_for_signup(email: str) -> Tenant:
    tenant_name = _guess_tenant_name_from_email(email)
    trial_ends_at = datetime.utcnow() + timedelta(days=7)
    
    try:
        with SessionLocal() as db:
            _log(f"Creating tenant for {email}...")
            tenant = Tenant(name=tenant_name, plan="starter", trial_ends_at=trial_ends_at)
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
            _log(f"Tenant created: id={tenant.id}, name={tenant.name}")
            return tenant
    except Exception as e:
        _log(f"Failed to create tenant for {email}", e)
        raise


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return f"{binascii.hexlify(salt).decode()}:{binascii.hexlify(derived).decode()}"


def _verify_passlib_hash(plain_password: str, hashed_password: str) -> bool:
    try:
        from passlib.context import CryptContext

        ctx = CryptContext(
            schemes=["pbkdf2_sha256", "bcrypt_sha256", "bcrypt"],
            deprecated="auto",
        )
        return ctx.verify(plain_password, hashed_password)
    except Exception:
        return False


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if ":" in hashed_password:
     mail = normalize_email(email)
    _log(f"Attempting to create user: {email}")
    
    try:
        existing = get_user_by_email(email)
        if existing:
            _log(f"User already exists: {email}")
            return None

        _log(f"User does not exist, creating tenant...")
        tenant = _get_or_create_tenant_for_signup(email)
        _log(f"Tenant ready, creating user record...")
        
        hashed = hash_password(password)
        user = User(email=email, password_hash=hashed, tenant_id=tenant.id, role="admin")

        with SessionLocal() as db:
            db.add(user)
            db.commit()
            db.refresh(user)
            _log(f"User created: id={user.id}, email={email}")
        
        return user
    except Exception as e:
        error_msg = f"Erro ao criar usuário: {str(e)}"
        _log(error_msg, e)
        if DEBUG_MODE:
            # In debug mode, show full error
            raise RuntimeError(f"{error_msg}\n[DEBUG] {type(e).__name__}: {str(e)}") from e
        else:
            # In production, show generic error
            raise RuntimeError(error_msg) from empting to create user: {email}")
    
    try:
        existing = get_user_by_email(email)
        if existing:
            _log(f"User already exists: {email}")
            return None

        _log(f"User does not exist, creating tenant...")
        tenant = _get_or_create_tenant_for_signup(email)
        _log(f"Tenant ready, creating user record...")
        
        hashed = hash_password(password)
        user = User(email=email, password_hash=hashed, tenant_id=tenant.id, role="admin")

        with SessionLocal() as db:
            db.add(user)
            db.commit()
            db.refresh(user)
            _log(f"User created: id={user.id}, email={email}")
        
        return user
    except Exception as e:
        error_msg = f"Erro ao criar usuário: {str(e)}"
        _log(error_msg, e)
        if DEBUG_MODE:
            # In debug mode, show full error
            raise RuntimeError(f"{error_msg}\n[DEBUG] {type(e).__name__}: {str(e)}") from e
        else:
            # In production, show generic error
            raise RuntimeError(error_msg) from e


def list_tenant_users(tenant_id: int) -> list[User]:
    with SessionLocal() as db:
        statement = select(User).where(User.tenant_id == int(tenant_id)).order_by(User.created_at.asc())
        return list(db.scalars(statement).all())


def get_tenant_by_id(tenant_id: int) -> Tenant | None:
    with SessionLocal() as db:
        return db.get(Tenant, int(tenant_id))


def update_tenant_profile(tenant_id: int, *, name: str | None = None, billing_email: str | None = None) -> Tenant | None:
    with SessionLocal() as db:
        tenant = db.get(Tenant, int(tenant_id))
        if not tenant:
            return None
        if name is not None:
            tenant.name = str(name).strip() or tenant.name
        if billing_email is not None:
            cleaned = (billing_email or "").strip().lower()
            tenant.billing_email = cleaned or None
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant


def set_tenant_plan(tenant_id: int, plan: str, subscription_status: str = "active", trial_days: int | None = None) -> Tenant | None:
    with SessionLocal() as db:
        tenant = db.get(Tenant, int(tenant_id))
        if not tenant:
            return None
        tenant.plan = str(plan).strip().lower()
        tenant.subscription_status = str(subscription_status).strip().lower()
        if trial_days is not None:
            tenant.trial_ends_at = datetime.utcnow() + timedelta(days=int(trial_days))
        elif tenant.plan != "pro":
            tenant.trial_ends_at = None
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant


def create_tenant_invite(tenant_id: int, email: str, expires_minutes: int = 60 * 24 * 7) -> TenantInvite:
    code = secrets.token_urlsafe(7)[:10]
    invite = TenantInvite(
        tenant_id=int(tenant_id),
        email=normalize_email(email),
        code=code,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=int(expires_minutes)),
        used=False,
    )
    with SessionLocal() as db:
        db.add(invite)
        db.commit()
        db.refresh(invite)
        return invite


def accept_tenant_invite(email: str, code: str, password: str) -> User | None:
    email_n = normalize_email(email)
    if get_user_by_email(email_n):
        return None

    with SessionLocal() as db:
        statement = (
            select(TenantInvite)
            .where(
                TenantInvite.email == email_n,
                TenantInvite.code == str(code).strip(),
                TenantInvite.used.is_(false()),
                TenantInvite.expires_at >= datetime.utcnow(),
            )
            .order_by(TenantInvite.created_at.desc())
        )
        invite = db.scalar(statement)
        if not invite:
            return None

        user = User(
            email=email_n,
            password_hash=hash_password(password),
            tenant_id=invite.tenant_id,
            role="member",
            is_first_login=True,
        )
        invite.used = True
        db.add(user)
        db.add(invite)
        db.commit()
        db.refresh(user)
        return user


def authenticate_user(email: str, password: str):
    user = get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_password_reset_token(email: str, expires_minutes: int = 30):
    user = get_user_by_email(email)
    if not user:
        return None

    code = f"{secrets.randbelow(10**6):06d}"
    expires_at = datetime.utcnow() + timedelta(minutes=expires_minutes)
    token = PasswordResetToken(
        user_id=user.id,
        code=code,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
        used=False,
    )

    with SessionLocal() as db:
        db.add(token)
        db.commit()
        db.refresh(token)
    return token


def _get_valid_password_reset_token(email: str, code: str):
    user = get_user_by_email(email)
    if not user:
        return None

    with SessionLocal() as db:
        statement = (
            select(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.code == code,
                PasswordResetToken.used.is_(false()),
                PasswordResetToken.expires_at >= datetime.utcnow(),
            )
            .order_by(PasswordResetToken.created_at.desc())
        )
        return db.scalar(statement)


def reset_password_with_code(email: str, code: str, new_password: str):
    token = _get_valid_password_reset_token(email, code)
    if not token:
        return None

    with SessionLocal() as db:
        user = db.get(User, token.user_id)
        if not user:
            return None
        user.password_hash = hash_password(new_password)
        token.used = True
        db.add(user)
        db.add(token)
        db.commit()
        db.refresh(user)
        return user


def mark_user_welcome_completed(user_id: int):
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user and user.is_first_login:
            user.is_first_login = False
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
