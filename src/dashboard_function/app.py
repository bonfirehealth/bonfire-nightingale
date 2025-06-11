import os
import json
import boto3
import psycopg2
from jinja2 import Environment, FileSystemLoader

# --- Configuration ---
DB_HOST = os.environ['DB_HOST']
DB_PORT = os.environ['DB_PORT']
DB_NAME = os.environ['DB_NAME']
DB_CREDENTIALS_SECRET_ARN = os.environ['DB_CREDENTIALS_SECRET_ARN']

# Jinja2 environment
file_loader = FileSystemLoader('templates')
env = Environment(loader=file_loader)

# Global connection for Lambda reuse
db_conn = None

def get_db_credentials():
    """Lấy thông tin đăng nhập DB từ AWS Secrets Manager."""
    secrets_client = boto3.client("secretsmanager")
    response = secrets_client.get_secret_value(SecretId=DB_CREDENTIALS_SECRET_ARN)
    return json.loads(response["SecretString"])

def get_db_connection():
    """Thiết lập hoặc tái sử dụng kết nối DB."""
    global db_conn
    if db_conn is None or db_conn.closed:
        creds = get_db_credentials()
        try:
            db_conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=creds['username'],
                password=creds['password']
            )
            print("Database connection established.")
        except psycopg2.Error as e:
            print(f"Database connection failed: {e}")
            raise
    return db_conn

def fetch_dashboard_metrics(cursor):
    """Lấy tất cả các chỉ số từ DB bằng một vài câu query."""
    metrics = {}
    
    # 1. MAU (Monthly Active Users)
    cursor.execute("""
        SELECT COUNT(DISTINCT parent_id)
        FROM messages
        WHERE sender = 'user' AND created_at >= NOW() - INTERVAL '30 days';
    """)
    metrics['mau'] = cursor.fetchone()[0]

    # 2. New Users (Last 30 days)
    cursor.execute("""
        SELECT COUNT(id)
        FROM parents
        WHERE created_at >= NOW() - INTERVAL '30 days';
    """)
    metrics['new_users_30d'] = cursor.fetchone()[0]

    # 3. Trial Conversion Rate
    cursor.execute("""
        SELECT
            COUNT(id) FILTER (WHERE subscription_status = 'active_paid') AS paid_users,
            COUNT(id) FILTER (WHERE subscription_status IN ('trial_opted_out', 'trial_expired', 'cancelled')) AS finished_trial_users
        FROM parents;
    """)
    result = cursor.fetchone()
    paid_users = result[0]
    finished_trial_users = result[1]
    total_trial_outcomes = paid_users + finished_trial_users
    metrics['trial_conversion_rate'] = paid_users / total_trial_outcomes if total_trial_outcomes > 0 else 0

    # 4. Total Coaching Sessions (Last 30 days)
    cursor.execute("""
        SELECT COUNT(id)
        FROM coaching_sessions
        WHERE session_start_time >= NOW() - INTERVAL '30 days';
    """)
    metrics['coaching_sessions_30d'] = cursor.fetchone()[0]
    
    return metrics

def fetch_recent_activity(cursor, limit=50):
    """Lấy hoạt động gần đây của người dùng."""
    cursor.execute("""
        WITH last_messages AS (
            SELECT
                parent_id,
                content,
                created_at,
                ROW_NUMBER() OVER(PARTITION BY parent_id ORDER BY created_at DESC) as rn
            FROM messages
            WHERE sender = 'user'
        )
        SELECT
            p.full_name,
            p.whatsapp_id,
            lm.content as last_message_content,
            lm.created_at as last_message_at
        FROM last_messages lm
        JOIN parents p ON lm.parent_id = p.id
        WHERE lm.rn = 1
        ORDER BY lm.created_at DESC
        LIMIT %s;
    """, (limit,))
    
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

def lambda_handler(event, context):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            metrics = fetch_dashboard_metrics(cursor)
            recent_activity = fetch_recent_activity(cursor)
            
        # Render HTML
        template = env.get_template('dashboard.html')
        html_body = template.render(
            metrics=metrics,
            recent_activity=recent_activity
        )
        
        return {
            'statusCode': 200,
            'headers': { 'Content-Type': 'text/html' },
            'body': html_body
        }
        
    except Exception as e:
        print(f"An error occurred: {e}")
        # Trả về lỗi 500 nếu có vấn đề
        return {
            'statusCode': 500,
            'headers': { 'Content-Type': 'text/html' },
            'body': '<h1>Internal Server Error</h1><p>Could not retrieve dashboard data.</p>'
        }