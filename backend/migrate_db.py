
import sqlite3
import os

DB_PATH = '/home/Larry/code/Ziqiu/LabelSystem/backend/instance/labelsystem.db'

def add_column_if_not_exists(cursor, table, column, definition):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"Added column {column} to {table}")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print(f"Column {column} already exists in {table}")
        else:
            print(f"Error adding {column} to {table}: {e}")

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Add columns to image_analysis table
    columns_to_add = [
        ('overall_quality', 'VARCHAR(50)'),
        ('has_artifacts', 'BOOLEAN'),
        ('has_banding_artifact', 'BOOLEAN'),
        ('has_susceptibility_artifact', 'BOOLEAN')
    ]

    for col, definition in columns_to_add:
        add_column_if_not_exists(cursor, 'image_analysis', col, definition)

    conn.commit()
    conn.close()
    print("Migration completed.")

if __name__ == "__main__":
    migrate()
