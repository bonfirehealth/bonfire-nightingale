import os
import json
import base64

import boto3
import psycopg2
from jinja2 import Environment, FileSystemLoader

# --- Configuration ---
DB_HOST = os.environ['DB_HOST']
DB_PORT = os.environ['DB_PORT']
DB_NAME = os.environ['DB_NAME']
DB_CREDENTIALS_SECRET_ARN = os.environ['DB_CREDENTIALS_SECRET_ARN']
APPLICATION_SECRETS_ARN = os.environ.get("APPLICATION_SECRETS_ARN")

# Jinja2 environment
file_loader = FileSystemLoader('templates')
env = Environment(loader=file_loader)

# Global connection for Lambda reuse
db_conn = None

EXCLUDED_PARENT_IDS = [10, 24]

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
    # cursor.execute("""
    #     SELECT
    #         COUNT(id) FILTER (WHERE subscription_status = 'active_paid') AS paid_users,
    #         COUNT(id) FILTER (WHERE subscription_status IN ('trialing', 'trial_opted_out', 'trial_expired', 'cancelled')) AS finished_trial_users
    #     FROM parents;
    # """)
    # result = cursor.fetchone()
    # paid_users = result[0]
    # finished_trial_users = result[1]
    # total_trial_outcomes = paid_users + finished_trial_users
    # metrics['trial_conversion_rate'] = paid_users / total_trial_outcomes if total_trial_outcomes > 0 else 0
    metrics['trial_conversion_rate'] = 0

    # 4. Total messages initiated
    cursor.execute("""
        SELECT COUNT(id)
        FROM messages 
        WHERE sender = 'user'
        AND (parent_id IS NULL OR parent_id NOT IN %s);
    """, (tuple(EXCLUDED_PARENT_IDS),))
    metrics['total_messages_initiated'] = cursor.fetchone()[0]
    
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

cached_dashboard_creds = None

def get_dashboard_credentials():
    """Lấy và cache thông tin đăng nhập dashboard từ Secrets Manager."""
    global cached_dashboard_creds
    if cached_dashboard_creds:
        return cached_dashboard_creds
    
    print("Fetching dashboard credentials from Secrets Manager.")
    secrets_client = boto3.client("secretsmanager")
    response = secrets_client.get_secret_value(SecretId=APPLICATION_SECRETS_ARN)
    cached_dashboard_creds = json.loads(response["SecretString"])
    return cached_dashboard_creds

def check_auth(event: dict) -> bool:
    """Kiểm tra thông tin Basic Authentication."""
    try:
        # Lấy thông tin đăng nhập đúng từ secret
        correct_creds = get_dashboard_credentials()
        correct_user = correct_creds.get("NIGHTINGALE_DASHBOARD_USERNAME")
        correct_pass = correct_creds.get("NIGHTINGALE_DASHBOARD_PASSWORD")

        # Lấy header Authorization từ request
        auth_header = event.get('headers', {}).get('authorization')
        if not auth_header or not auth_header.lower().startswith('basic '):
            return False
        
        # Decode Base64
        encoded_creds = auth_header.split(' ')[1]
        decoded_creds = base64.b64decode(encoded_creds).decode('utf-8')
        
        # Tách username và password
        provided_user, provided_pass = decoded_creds.split(':', 1)

        # So sánh (cách an toàn là dùng so sánh hằng thời gian, nhưng ở đây là đủ)
        return provided_user == correct_user and provided_pass == correct_pass

    except Exception as e:
        print(f"Authentication check failed: {e}")
        return False

def lambda_handler(event, context):
    # --- BƯỚC KIỂM TRA AUTHENTICATION ---
    if not check_auth(event):
        print(f"Authentication failed. Event: {event}")
        # Nếu sai, trả về lỗi 401 để trình duyệt hiện popup đăng nhập
        return {
            'statusCode': 401,
            'headers': {
                'WWW-Authenticate': 'Basic realm="Nightingale AI Dashboard"'
            },
            'body': 'Unauthorized'
        }

    # --- Nếu pass, chạy logic như cũ ---
    print("Authentication successful. Proceeding to generate dashboard.")
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            metrics = fetch_dashboard_metrics(cursor)
            recent_activity = fetch_recent_activity(cursor)
            
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
        print(f"An error occurred after authentication: {e}")
        return {
            'statusCode': 500,
            'headers': { 'Content-Type': 'text/html' },
            'body': '<h1>Internal Server Error</h1><p>Could not retrieve dashboard data.</p>'
        }
