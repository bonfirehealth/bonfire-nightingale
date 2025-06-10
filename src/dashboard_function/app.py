import os
import json
import base64
import boto3
from jinja2 import Environment, FileSystemLoader
from botocore.exceptions import ClientError

# --- Khởi tạo ---
# Boto3 clients
dynamodb = boto3.resource('dynamodb')

# Jinja2 environment
file_loader = FileSystemLoader('templates')
env = Environment(loader=file_loader)

# Lấy thông tin từ biến môi trường
METRICS_TABLE_NAME = os.environ['METRICS_TABLE_NAME']
METRIC_NAME = os.environ['COUNTER_METRIC_NAME']
ACTIVE_USERS_TABLE_NAME = os.environ['ACTIVE_USERS_TABLE_NAME']
PAGE_SIZE = 25 # Số lượng user hiển thị mỗi trang

metrics_table = dynamodb.Table(METRICS_TABLE_NAME)
active_users_table = dynamodb.Table(ACTIVE_USERS_TABLE_NAME)


def get_total_active_users():
    """Đọc số tổng từ bảng Metrics (nhanh và hiệu quả)"""
    try:
        response = metrics_table.get_item(Key={'activeUserCount': METRIC_NAME})
        if 'Item' in response:
            return int(response['Item']['metricValue'])
    except ClientError as e:
        print(f"Error reading total count: {e}")
    return 0

def get_active_users_page(page_size, start_key=None):
    """Lấy một trang danh sách user chi tiết bằng cách Scan"""
    scan_kwargs = {
        'Limit': page_size,
        # Chỉ lấy các thuộc tính cần thiết để giảm lượng dữ liệu đọc
        'ProjectionExpression': "userId, userName"
    }
    if start_key:
        scan_kwargs['ExclusiveStartKey'] = start_key
        
    try:
        response = active_users_table.scan(**scan_kwargs)
        users = response.get('Items', [])
        # Lấy token cho trang tiếp theo
        next_page_token = response.get('LastEvaluatedKey', None)
        return users, next_page_token
    except ClientError as e:
        print(f"Error scanning for active users: {e}")
        return [], None

def lambda_handler(event, context):
    print(f"Received event: {event}")
    
    # Lấy tổng số người dùng
    total_users_count = get_total_active_users()
    
    # Xử lý pagination
    next_token_str = event.get('queryStringParameters', {}).get('nextToken')
    start_key = None
    if next_token_str:
        # DynamoDB token được truyền qua URL, nên cần decode
        try:
            start_key = json.loads(base64.b64decode(next_token_str).decode('utf-8'))
        except Exception as e:
            print(f"Invalid nextToken format: {e}")

    # Lấy danh sách user cho trang hiện tại
    users_list, next_page_key = get_active_users_page(PAGE_SIZE, start_key)
    
    # Chuẩn bị token cho trang tiếp theo để truyền vào template
    # Token cần được encode để an toàn khi đặt trong URL
    next_token_for_url = None
    if next_page_key:
        next_token_for_url = base64.b64encode(json.dumps(next_page_key).encode('utf-8')).decode('utf-8')

    # Render HTML
    template = env.get_template('dashboard.html')
    html_body = template.render(
        total_users=total_users_count,
        users=users_list,
        next_token=next_token_for_url
    )
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'text/html',
        },
        'body': html_body
    }