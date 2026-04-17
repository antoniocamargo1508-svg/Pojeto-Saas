import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def _ensure_schema():
    inspector = inspect(engine)

    # Ensure multi-tenant baseline exists (tenant 1 = default)
    if "tenants" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("tenants")]
        if "plan" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN plan VARCHAR NOT NULL DEFAULT 'starter'"))
            columns.append("plan")
        if "subscription_status" not in columns:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE tenants ADD COLUMN subscription_status VARCHAR NOT NULL DEFAULT 'inactive'")
                )
        if "billing_email" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN billing_email VARCHAR"))
        if "trial_ends_at" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN trial_ends_at DATETIME"))

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tenants (id, name, created_at, plan, subscription_status, billing_email) "
                    "SELECT 1, 'Default', CURRENT_TIMESTAMP, 'starter', 'inactive', NULL "
                    "WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE id = 1)"
                )
            )
        if "plan" in columns:
            with engine.begin() as conn:
                conn.execute(text("UPDATE tenants SET plan = 'starter' WHERE plan = 'free'"))

    if "users" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("users")]
        if "tenant_id" not in columns:
            alter_sql = (
                "ALTER TABLE users ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"
                if engine.dialect.name == "sqlite"
                else "ALTER TABLE users ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"
            )
            with engine.begin() as conn:
                conn.execute(text(alter_sql))
            columns.append("tenant_id")
        if "is_first_login" not in columns:
            alter_sql = (
                "ALTER TABLE users ADD COLUMN is_first_login BOOLEAN NOT NULL DEFAULT 1"
                if engine.dialect.name == "sqlite"
                else "ALTER TABLE users ADD COLUMN is_first_login BOOLEAN NOT NULL DEFAULT TRUE"
            )
            with engine.begin() as conn:
                conn.execute(text(alter_sql))
            columns.append("is_first_login")
        if "role" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR NOT NULL DEFAULT 'admin'"))

    if "uploads" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("uploads")]
        if "tenant_id" not in columns:
            alter_sql = (
                "ALTER TABLE uploads ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"
                if engine.dialect.name == "sqlite"
                else "ALTER TABLE uploads ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"
            )
            with engine.begin() as conn:
                conn.execute(text(alter_sql))

    if "financial_records" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("financial_records")]
        if "tenant_id" not in columns:
            alter_sql = (
                "ALTER TABLE financial_records ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"
                if engine.dialect.name == "sqlite"
                else "ALTER TABLE financial_records ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"
            )
            with engine.begin() as conn:
                conn.execute(text(alter_sql))

    # tenant_invites table is created by metadata; no ALTER needed here.


def _reset_database_if_requested() -> None:
    if os.getenv("RESET_DATABASE", "").strip() != "1":
        return

    if DATABASE_URL.startswith("sqlite:///"):
        sqlite_path = DATABASE_URL.replace("sqlite:///", "", 1)
        if os.path.exists(sqlite_path):
            os.remove(sqlite_path)


def init_db():
    _reset_database_if_requested()
    import mvp.models

    Base.metadata.create_all(bind=engine)
    _ensure_schema()
