from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """
    This is the foundation for all SQLAlchemy models.
    Every table created will inherit from this class.
    """
    pass