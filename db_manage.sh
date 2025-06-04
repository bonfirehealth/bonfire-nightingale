#!/bin/bash

# db_manage.sh - Script to manage Nightingale PostgreSQL database

# --- Configuration ---
# Lấy từ biến môi trường hoặc điền trực tiếp (không khuyến khích cho production credentials)
# Nếu chạy script này từ EC2 instance có IAM role được phép truy cập RDS,
# bạn có thể không cần password nếu dùng IAM authentication.
# Đối với Aurora, bạn thường sẽ lấy username/password từ Secrets Manager.
# Script này giả định bạn có psql client và các biến kết nối.

DB_HOST="${PGHOST:-nightingaledatabasestack-d-databasecluster68fc2945-aty8lekjfku8.cluster-cd0csowcqlz1.ap-southeast-1.rds.amazonaws.com}" # e.g., nightingale-dev.cluster-xxxx.ap-southeast-1.rds.amazonaws.com
DB_PORT="${PGPORT:-5432}"
DB_USER="${PGUSER:-bonfire}" # Username bạn cấu hình cho RDS (ví dụ: từ context cdk.json)
DB_NAME="${PGDATABASE:-nightingale_dev}" # Tên DB, ví dụ: nightingale_dev hoặc nightingale_prod
# PGPASSWORD có thể được set làm biến môi trường trước khi chạy script.
# export PGPASSWORD="your_password_here"

SCHEMA_FILE="schema.sql"

# --- Helper Functions ---
print_usage() {
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  connect                Connect to the database using psql."
    echo "  apply_schema           Apply (or re-apply) the schema from $SCHEMA_FILE."
    echo "                         WARNING: This will drop and recreate tables if they exist (idempotent but destructive for data)."
    echo "  create_schema_safe     Apply schema, only creating tables if they do NOT exist."
    echo "  show_tables            List all tables in the database."
    echo "  backup <backup_file>   Create a plain-text SQL dump of the database."
    echo "  restore <backup_file>  Restore database from a plain-text SQL dump."
    echo "                         WARNING: This usually involves dropping existing objects first."
    echo "  reset_dev_db           (For Dev Only) Drops all tables and re-applies schema."
    echo "                         VERY DESTRUCTIVE. Prompts for confirmation."
    echo ""
    echo "Ensure psql client is installed and configured."
    echo "Set PGPASSWORD environment variable or use .pgpass file for password."
    echo "Connection variables (PGHOST, PGPORT, PGUSER, PGDATABASE) can be overridden."
}

confirm_action() {
    read -r -p "$1 [y/N]: " response
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0 # True
            ;;
        *)
            return 1 # False
            ;;
    esac
}

# --- Main Commands ---
connect_db() {
    echo "Connecting to database: $DB_NAME on $DB_HOST..."
    psql "postgresql://$DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
}

apply_schema() {
    if ! confirm_action "This will apply '$SCHEMA_FILE'. It might DROP and RECREATE tables if they exist, leading to DATA LOSS. Are you sure?"; then
        echo "Action cancelled."
        return
    fi
    echo "Applying schema from $SCHEMA_FILE to $DB_NAME..."
    # Đọc file schema.sql, bỏ qua các dòng comment bắt đầu bằng -- (trừ khi có lệnh SQL)
    # psql -v ON_ERROR_STOP=1 --username "$DB_USER" --host "$DB_HOST" --port "$DB_PORT" --dbname "$DB_NAME" -f "$SCHEMA_FILE"
    # Cách an toàn hơn là chạy từng lệnh CREATE TABLE IF NOT EXISTS
    # Tuy nhiên, schema.sql đã dùng CREATE TABLE IF NOT EXISTS.
    # Nếu muốn đảm bảo chạy lại hoàn toàn, bạn có thể cần drop tables trước (xem reset_dev_db)
    psql -v ON_ERROR_STOP=1 -U "$DB_USER" -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -f "$SCHEMA_FILE"
    if [ $? -eq 0 ]; then
        echo "Schema applied successfully."
    else
        echo "Error applying schema."
    fi
}

create_schema_safe() {
    echo "Safely applying schema (CREATE IF NOT EXISTS) from $SCHEMA_FILE to $DB_NAME..."
    # schema.sql đã được thiết kế để an toàn với CREATE TABLE IF NOT EXISTS
    psql -v ON_ERROR_STOP=1 -U "$DB_USER" -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -f "$SCHEMA_FILE"
    if [ $? -eq 0 ]; then
        echo "Schema applied safely."
    else
        echo "Error applying schema safely."
    fi
}


show_tables() {
    echo "Tables in database $DB_NAME:"
    psql -U "$DB_USER" -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -c "\dt"
}

backup_db() {
    BACKUP_FILE="$1"
    if [ -z "$BACKUP_FILE" ]; then
        echo "Error: Backup file name not specified."
        echo "Usage: $0 backup <backup_filename.sql>"
        return 1
    fi
    echo "Backing up database $DB_NAME to $BACKUP_FILE..."
    pg_dump -U "$DB_USER" -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" --clean --if-exists --no-owner --no-privileges -f "$BACKUP_FILE"
    # Dùng --no-owner và --no-privileges để dễ restore hơn trên các DB khác nhau
    # --clean --if-exists sẽ thêm lệnh DROP IF EXISTS trước CREATE
    if [ $? -eq 0 ]; then
        echo "Database backup successful: $BACKUP_FILE"
    else
        echo "Database backup failed."
    fi
}

restore_db() {
    RESTORE_FILE="$1"
    if [ -z "$RESTORE_FILE" ]; then
        echo "Error: Restore file name not specified."
        echo "Usage: $0 restore <backup_filename.sql>"
        return 1
    fi
    if [ ! -f "$RESTORE_FILE" ]; then
        echo "Error: Restore file '$RESTORE_FILE' not found."
        return 1
    fi

    if ! confirm_action "WARNING: This will restore '$RESTORE_FILE' to '$DB_NAME'. This usually involves dropping existing objects and can lead to DATA LOSS. Are you sure?"; then
        echo "Restore cancelled."
        return
    fi

    echo "Restoring database $DB_NAME from $RESTORE_FILE..."
    # Thông thường, file backup được tạo bởi pg_dump --clean sẽ tự drop objects
    psql -v ON_ERROR_STOP=1 -U "$DB_USER" -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -f "$RESTORE_FILE"
    if [ $? -eq 0 ]; then
        echo "Database restore successful."
    else
        echo "Database restore failed."
    fi
}

reset_dev_database() {
    if [[ "$DB_NAME" != *"dev"* && "$DB_NAME" != *"test"* ]]; then # Một biện pháp an toàn nhỏ
        echo "Error: This command is intended for development/testing databases only (name should contain 'dev' or 'test')."
        echo "Current DB_NAME: $DB_NAME"
        return 1
    fi

    if ! confirm_action "EXTREME WARNING: This will DROP ALL TABLES in '$DB_NAME' and re-apply the schema. ALL DATA WILL BE LOST. This is for DEV/TEST ONLY. Are you sure?"; then
        echo "Reset cancelled."
        return
    fi

    echo "Resetting development database $DB_NAME..."
    # Lấy danh sách tất cả các bảng và drop chúng
    TABLES_TO_DROP=$(psql -U "$DB_USER" -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -t -c "SELECT string_agg('DROP TABLE IF EXISTS ' || quote_ident(tablename) || ' CASCADE;', ' ') FROM pg_tables WHERE schemaname = 'public';")

    if [ -n "$TABLES_TO_DROP" ]; then
        echo "Dropping existing tables..."
        psql -v ON_ERROR_STOP=1 -U "$DB_USER" -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -c "$TABLES_TO_DROP"
        if [ $? -ne 0 ]; then
            echo "Error dropping tables. Aborting reset."
            return 1
        fi
    else
        echo "No tables found to drop."
    fi

    echo "Re-applying schema..."
    apply_schema # Gọi lại hàm apply_schema (sẽ có confirm riêng)
    echo "Development database reset complete."
}


# --- Command Dispatcher ---
COMMAND="$1"
shift # Loại bỏ command khỏi danh sách đối số

case "$COMMAND" in
    connect)
        connect_db
        ;;
    apply_schema)
        apply_schema
        ;;
    create_schema_safe)
        create_schema_safe
        ;;
    show_tables)
        show_tables
        ;;
    backup)
        backup_db "$@"
        ;;
    restore)
        restore_db "$@"
        ;;
    reset_dev_db)
        reset_dev_database
        ;;
    *)
        print_usage
        exit 1
        ;;
esac

exit 0