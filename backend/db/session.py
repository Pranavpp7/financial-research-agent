import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

# Build the connection URL from .env variables
DATABASE_URL = (
    f"postgresql+psycopg2://"
    f"{os.getenv('POSTGRES_USER')}:"
    f"{os.getenv('POSTGRES_PASSWORD')}@"
    f"{os.getenv('POSTGRES_HOST')}:"
    f"{os.getenv('POSTGRES_PORT')}/"
    f"{os.getenv('POSTGRES_DB')}"
)

# Create the engine — this is the core connection to PostgreSQL
engine = create_engine(
    DATABASE_URL,
    echo=False,      # set True to see all SQL queries in terminal
    pool_pre_ping=True  # checks connection is alive before using it
)

# SessionLocal is a factory that creates database sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db():
    """
    Provides a database session.
    Always closes the session after use — even if an error occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection():
    """
    Quick test to verify database connection is working.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"Connected to PostgreSQL successfully")
            print(f"Version: {version}")
            return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False


if __name__ == "__main__":
    test_connection()