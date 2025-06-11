import os
import boto3

dynamodb = boto3.resource('dynamodb')
table_name = os.environ['METRICS_TABLE_NAME']
metric_name = os.environ['COUNTER_METRIC_NAME']
metrics_table = dynamodb.Table(table_name)

def lambda_handler(event, context):
    print(f"Received {len(event['Records'])} records from DynamoDB Stream.")
    
    insert_count = 0
    remove_count = 0

    for record in event['Records']:
        event_name = record['eventName']
        
        # Chỉ quan tâm đến sự kiện INSERT (user mới active) hoặc REMOVE (session hết hạn)
        if event_name == 'INSERT':
            insert_count += 1
        elif event_name == 'REMOVE':
            # Rất quan trọng: Chỉ giảm bộ đếm nếu item bị xóa bởi TTL của DynamoDB,
            # không phải do người dùng xóa thủ công.
            # Identity của TTL event là từ service của DynamoDB.
            if record.get('userIdentity', {}).get('type') == 'Service':
                remove_count += 1
            else:
                print(f"Skipping manual REMOVE event for item: {record['dynamodb']['Keys']}")

    print(f"Counted inserts: {insert_count}, Counted removes: {remove_count}")

    # Cập nhật bộ đếm trong bảng Metrics
    # Sử dụng atomic counter để đảm bảo tính nhất quán
    total_change = insert_count - remove_count
    
    if total_change != 0:
        try:
            response = metrics_table.update_item(
                Key={'activeUserCount': metric_name},
                # 'ADD' sẽ tạo attribute nếu chưa tồn tại và gán giá trị là total_change,
                # hoặc cộng/trừ vào giá trị hiện có.
                UpdateExpression='ADD metricValue :val',
                ExpressionAttributeValues={':val': total_change},
                ReturnValues='UPDATED_NEW'
            )
            print(f"Updated counter. New value: {response['Attributes']['metricValue']}")
        except Exception as e:
            print(f"Error updating counter: {e}")
            # Có thể thêm logic retry hoặc gửi thông báo lỗi ở đây
            raise e
            
    return {
        'statusCode': 200,
        'body': 'Processed stream records successfully.'
    }