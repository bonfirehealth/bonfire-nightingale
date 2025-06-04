import os
import logging

import psycopg2
from config import get_secret

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DB_HOST = os.environ.get('DB_HOST')
DB_PORT = os.environ.get('DB_PORT')
DB_NAME = os.environ.get('DB_NAME')
DB_CREDENTIALS_SECRET_ARN = os.environ.get('DB_CREDENTIALS_SECRET_ARN')

# --- Database Connection ---
def get_db_connection() -> psycopg2.extensions.connection:
    db_conn = None
    if db_conn and db_conn.closed == 0:
         try:
            cur = db_conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return db_conn
         except psycopg2.Error:
            logger.info("Database connection was closed or unusable, reconnecting.")
            db_conn = None

    if not db_conn or db_conn.closed != 0:
        try:
            db_creds = get_secret(DB_CREDENTIALS_SECRET_ARN)
            db_conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=db_creds['username'], password=db_creds['password']
            )
            logger.info("Successfully connected to PostgreSQL database for scheduled tasks.")
        except Exception as e:
            logger.error(f"Error connecting to database for scheduled tasks: {e}")
            raise
    return db_conn

