from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Define standard naming conventions for PostgreSQL constraints and indexes.
# This is critical for Alembic to reliably autogenerate and manage migrations
# without running into naming conflicts or unnamed constraints.
POSTGRES_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Create a shared MetaData instance with the naming convention
metadata_obj = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy 2.0 declarative models in the application.
    
    Inheriting from this class ensures that all models share the same
    MetaData instance, which is required for Alembic autogenerate to detect
    all tables and relationships correctly.
    """
    metadata = metadata_obj