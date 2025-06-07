import psycopg2
from config import logger, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

db_conn = None

def get_db_connection():
    """Establishes a reusable database connection for the Lambda invocation."""
    global db_conn
    if db_conn is None or db_conn.closed:
        try:
            db_conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            logger.info("Database connection established successfully.")
        except psycopg2.Error as e:
            logger.error(f"Error connecting to PostgreSQL database: {e}")
            raise
    return db_conn