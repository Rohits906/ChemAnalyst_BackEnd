import sqlite3
import os

try:
    conn = sqlite3.connect('db.sqlite3')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email FROM auth_user")
    rows = cursor.fetchall()
    print("---DB_USERS---")
    for row in rows:
        print(row)
    print("--------------")
    conn.close()
except Exception as e:
    print(f"Error accessing database: {e}")
