import psycopg2
import os

# --- IMPORTANT ---
# Replace with the password you saved from Step 2
DB_PASSWORD = "YOUR_SECURE_PASSWORD_HERE"

print("Attempting to connect to secure PostgreSQL server...")

try:
    # The connection string MUST include sslmode='require'.
    # If you use sslmode='disable', the server will reject the connection.
    conn = psycopg2.connect(
        host="localhost",
        port="5432",
        user="postgres",
        dbname="postgres",
        password=DB_PASSWORD,
        sslmode='require' 
    )

    cursor = conn.cursor()
    
    # Execute a simple query to verify the connection
    cursor.execute("SELECT version();")
    db_version = cursor.fetchone()
    
    print("\n✅ Connection successful!")
    print(f"   PostgreSQL Version: {db_version[0]}")

    cursor.close()
    conn.close()

except psycopg2.OperationalError as e:
    print("\n❌ Connection failed.")
    print("   This might be expected if SSL is not correctly configured.")
    print(f"   Error: {e}")
except Exception as e:
    print(f"\n❌ An unexpected error occurred: {e}")