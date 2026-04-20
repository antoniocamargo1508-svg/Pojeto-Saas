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
    """Ensure all required tables and columns exist, creating them if necessary."""
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        # Create all ORM tables if they don't exist
        if not existing_tables:
            Base.metadata.create_all(bind=engine)
            existing_tables = inspector.get_table_names()

        # Ensure multi-tenant baseline exists (tenant 1 = default)
        if "tenants" not in existing_tables:
            Base.metadata.tables["tenants"].create(bind=engine, checkfirst=True)

        if "tenants" in existing_tables:
            columns = [col["name"] for col in inspector.get_columns("tenants")]
            if "plan" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE tenants ADD COLUMN plan VARCHAR NOT NULL DEFAULT 'starter'"))
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

            # Ensure default tenant exists
            with engine.begin() as conn:
                existing = conn.execute(
                    text("SELECT COUNT(*) FROM tenants WHERE id = 1")
                ).scalar()
                if not existing:
                    conn.execute(
                        text(
                            "INSERT INTO tenants (id, name, created_at, plan, subscription_status, billing_email) "
                            "VALUES (1, 'Default', CURRENT_TIMESTAMP, 'starter', 'inactive', NULL)"
                        )
                    )

        if "users" in existing_tables:
            columns = [col["name"] for col in inspector.get_columns("users")]
            if "tenant_id" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE users ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"))
            if "is_first_login" not in columns:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE users ADD COLUMN is_first_login BOOLEAN NOT NULL DEFAULT 1"
                            if engine.dialect.name == "sqlite"
                            else "ALTER TABLE users ADD COLUMN is_first_login BOOLEAN NOT NULL DEFAULT TRUE"
                        )
                    )
            if "role" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR NOT NULL DEFAULT 'admin'"))

        if "uploads" in existing_tables:
            columns = [col["name"] for col in inspector.get_columns("uploads")]
            if "tenant_id" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE uploads ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"))

        if "financial_records" in existing_tables:
            columns = [col["name"] for col in inspector.get_columns("financial_records")]
            if "tenant_id" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE financial_records ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"))

    except Exception as e:
        print(f"WARNING: Schema initialization had an issue: {e}. Attempting to continue...")


def _reset_database_if_requested() -> None:
    if os.getenv("RESET_DATABASE", "").strip() != "1":
        return

    if DATABASE_URL.startswith("sqlite:///"):
        sqlite_path = DATABASE_URL.replace("sqlite:///", "", 1)
        if os.path.exists(sqlite_path):
            os.remove(sqlite_path)


def init_db():
    """Initialize database: reset if requested, then create tables and schema."""
    _reset_database_if_requested()
    import mvp.models

    try:
        Base.metadata.create_all(bind=engine)
        _ensure_schema()
    except Exception as e:
        print(f"ERROR during database initialization: {e}")
        raise
