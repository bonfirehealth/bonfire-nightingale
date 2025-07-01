FROM python:3.11-slim

WORKDIR /app

# Cài đặt các thư viện hệ thống nếu cần
# RUN apt-get update && apt-get install -y ...

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    ENVIRONMENT_NAME=prod \
    LOG_LEVEL=info

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY .env .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]