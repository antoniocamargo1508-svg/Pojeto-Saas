from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Boolean
from sqlalchemy.orm import relationship
from mvp.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    plan = Column(String, nullable=False, default="starter")
    subscription_status = Column(String, nullable=False, default="inactive")
    billing_email = Column(String, nullable=True)
    trial_ends_at = Column(DateTime, nullable=True)

    users = relationship("User", back_populates="tenant")
    uploads = relationship("Upload", back_populates="tenant")
    records = relationship("FinancialRecord", back_populates="tenant")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_first_login = Column(Boolean, nullable=False, default=True)
    role = Column(String, nullable=False, default="admin")

    tenant = relationship("Tenant", back_populates="users")
    uploads = relationship("Upload", back_populates="user")
    records = relationship("FinancialRecord", back_populates="user")
    reset_tokens = relationship("PasswordResetToken", back_populates="user")


class TenantInvite(Base):
    __tablename__ = "tenant_invites"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    code = Column(String(10), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)

    tenant = relationship("Tenant")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    code = Column(String(6), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="reset_tokens")


class Upload(Base):
    __tablename__ = "uploads"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="completed")

    tenant = relationship("Tenant", back_populates="uploads")
    user = relationship("User", back_populates="uploads")
    records = relationship("FinancialRecord", back_populates="upload")


class FinancialRecord(Base):
    __tablename__ = "financial_records"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    upload_id = Column(Integer, ForeignKey("uploads.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(DateTime, nullable=False)
    category = Column(String, nullable=False)
    budgeted = Column(Float, nullable=True)
    actual = Column(Float, nullable=True)
    record_type = Column(String, nullable=False, default="expense")
    month_year = Column(String, nullable=False)

    upload = relationship("Upload", back_populates="records")
    user = relationship("User", back_populates="records")
    tenant = relationship("Tenant", back_populates="records")
