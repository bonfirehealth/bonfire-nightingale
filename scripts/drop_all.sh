#!/bin/bash

# Cấu hình kết nối
DB_NAME="your_database_name"
DB_USER="your_username"
DB_HOST="localhost"   # hoặc địa chỉ IP
DB_PORT="5432"

# Tùy chọn xác thực: bạn có thể thiết lập biến môi trường PGPASSWORD hoặc sử dụng ~/.pgpass
# export PGPASSWORD="your_password"

echo "Dropping all objects in schema 'public'..."

psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" <<EOF

-- Xóa tất cả triggers
DO \$\$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT event_object_table, trigger_name FROM information_schema.triggers WHERE trigger_schema = 'public') LOOP
        EXECUTE 'DROP TRIGGER IF EXISTS ' || quote_ident(r.trigger_name) || ' ON ' || quote_ident(r.event_object_table) || ' CASCADE';
    END LOOP;
END;
\$\$;

-- Xóa tất cả functions
DO \$\$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT routine_name, specific_name FROM information_schema.routines WHERE routine_schema = 'public' AND routine_type='FUNCTION') LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || quote_ident(r.routine_name) || ' CASCADE';
    END LOOP;
END;
\$\$;

-- Xóa tất cả tables
DO \$\$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END;
\$\$;

-- Xóa tất cả types (nếu có)
DO \$\$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT typname FROM pg_type WHERE typnamespace = 'public'::regnamespace AND typtype = 'e') LOOP
        EXECUTE 'DROP TYPE IF EXISTS ' || quote_ident(r.typname) || ' CASCADE';
    END LOOP;
END;
\$\$;

EOF

echo "✅ All tables, triggers, and functions dropped from schema 'public'."
