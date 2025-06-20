FROM python:3.11-slim

WORKDIR /app

# Cài đặt các thư viện hệ thống nếu cần
# RUN apt-get update && apt-get install -y ...

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# FastAPI thường chạy với uvicorn
# Biến môi trường PORT sẽ được Fargate cung cấp
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]