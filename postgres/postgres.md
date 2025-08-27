# **Production-Grade Secure PostgreSQL Deployment via Docker**

**Objective:** To deploy a persistent, encrypted, and password-protected PostgreSQL server. All data and configuration will reside in `/postgresql-secure/`, and the service will only be accessible from the host machine (`localhost`) for maximum security.

**Security Principles Adhered To:**
*   **Data Persistence:** Database files are stored on the host filesystem, surviving container restarts.
*   **Encrypted Transport:** All client-server communication is encrypted using TLS/SSL.
*   **Secure Credentials:** The superuser password is managed via Docker Secrets, never exposed in configuration files or environment variables.
*   **Network Isolation:** The database port is bound to `localhost`, preventing any external network access.

---

### **Table of Contents**
- [Step 1: Create Project Structure and Set Permissions in Root](#step-1-create-project-structure-and-set-permissions-in-root)
- [Step 2: Secure the `postgres` Password via Docker Secrets](#step-2-secure-the-postgres-password-via-docker-secrets)
- [Step 3: Provide TLS Certificates](#step-3-provide-tls-certificates)
- [Step 4: Create the Docker Compose Configuration File](#step-4-create-the-docker-compose-configuration-file)
- [Step 5: Launch and Verify the Service](#step-5-launch-and-verify-the-service)
- [Step 6: Connecting to Your Secure Instance](#step-6-connecting-to-your-secure-instance)

---

### **Step 1: Create Project Structure and Set Permissions in Root**

This step is critical. We will create the necessary directories directly in the root (`/`) filesystem and assign the correct ownership so that the PostgreSQL process inside the container can write to its data directory.

```bash
# 1. Create the complete directory structure using sudo
sudo mkdir -p /postgresql-secure/{data,secrets,certificates}

# 2. Change the ownership of the data directory.
# The official PostgreSQL container runs as the 'postgres' user, which has a User ID (UID) of 999.
# We must grant ownership of the data directory to this UID on the host machine.
sudo chown -R 999:999 /postgresql-secure/data

# 3. (Optional) Verify the permissions.
# The 'data' directory should be owned by '999'.
sudo ls -ld /postgresql-secure/data
```

**Why this is important:** Without `chown`, the non-root `postgres` user inside the container would be denied permission to write to the `/postgresql-secure/data` directory (which is owned by `root` by default), and the container would fail to start.

---

### **Step 2: Secure the `postgres` Password via Docker Secrets**

We will generate a strong password and store it in a file that Docker Compose will manage as a secret. Because the target directory is owned by `root`, we must use a specific command pattern to write the file.

```bash
# Navigate to the project directory for convenience
cd /postgresql-secure

# 1. Generate a strong, random password.
# The output is piped to `tee`, which is run with sudo to write the file.
openssl rand -base64 32 | sudo tee secrets/postgres_password > /dev/null

# 2. (Optional) Set strict permissions on the secret file for added security.
sudo chmod 600 secrets/postgres_password

# 3. (Optional) Display the password ONCE to save it in your password manager.
echo "Your secure PostgreSQL password is: $(sudo cat secrets/postgres_password)"
```



**Why this is important:** This method avoids placing plaintext passwords in your `docker-compose.yml` file or in shell history. Using `sudo tee` is necessary because standard output redirection (`>`) is processed by your user's shell *before* `sudo` is invoked, which would cause a "Permission Denied" error.

---

### **Step 3: Provide TLS Certificates**

For this guide, we will assume you have already generated the `private.key` and `public.crt` files from your Neo4j setup. We will securely copy them into place for PostgreSQL to use.

```bash
# Ensure you are in the /postgresql-secure directory.
cd /postgresql-secure

# 1. Copy your existing certificate and private key.
# Replace '/path/to/your/neo4j-certs' with the actual source.
sudo cp /path/to/your/neo4j-certs/public.crt certificates/
sudo cp /path/to/your/neo4j-certs/private.key certificates/

# 2. Set the ownership and permissions.
# The owner will be 'root' and the group will be '999' (the GID of the postgres user).
sudo chown root:999 certificates/*

# 3. Set permissions to '640' (rw-r-----).
# This allows the owner 'root' to manage the files and the 'postgres' group to read them.
sudo chmod 640 certificates/*

# 4. (Optional) Verify the permissions.
sudo ls -l certificates/
# Expected output should show permissions as -rw-r----- and owner/group as root/999.```
```

**Why this is important:** Reusing the same `localhost` certificate simplifies management. Setting restrictive file permissions (`chmod 600`) ensures that only the owner (`root`) can read or write the key and certificate files, which is a security best practice.

---

### **Step 4: Create the Docker Compose Configuration File**

This file defines the entire service, bringing together the data volumes, secrets, and security configurations.

Create the file `/postgresql-secure/docker-compose.yml` with the following content:

```yaml
# /postgresql-secure/docker-compose.yml

version: '3.8'

services:
  postgres:
    # Pinning a specific version is best practice for production
    image: postgres:16
    container_name: postgres_local_secure
    restart: unless-stopped

    # Security: Bind the port only to localhost (127.0.0.1) on the host machine.
    # This makes the database completely inaccessible from the network.
    ports:
      - "127.0.0.1:5432:5432"

    volumes:
      # Map the persistent data directory
      - ./data:/var/lib/postgresql/data
      # Map the certificates for SSL/TLS connections
      - ./certificates:/etc/ssl/certs:ro # 'ro' for read-only is more secure

    environment:
      # Instruct PostgreSQL to read the password from the secret file
      - POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password
      # Optional: Define the default user and database
      - POSTGRES_USER=postgres
      - POSTGRES_DB=postgres

    secrets:
      - postgres_password

    # Command to enforce SSL and point to the mounted certificates.
    # This is the core of the transport security configuration.
    command: >
      -c ssl=on
      -c ssl_cert_file=/etc/ssl/certs/public.crt
      -c ssl_key_file=/etc/ssl/certs/private.key

    healthcheck:
      # A reliable check to see if the database is ready for connections
      test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

secrets:
  postgres_password:
    file: ./secrets/postgres_password

```

---

### **Step 5: Launch and Verify the Service**

Now you are ready to start the secure PostgreSQL container.

```bash
# Ensure you are in the /postgresql-secure directory
cd /postgresql-secure

# 1. Start the service in detached mode (in the background)
sudo docker compose up -d

# 2. Check the status of the container.
# Wait for the STATUS column to show 'running (healthy)'. This may take a minute on first start.
sudo docker compose ps

# 3. (Optional) If you encounter issues, view the logs for troubleshooting.
sudo docker compose logs -f
```

### **Step 6: Connecting to Your Secure Instance**


#### Accessing from docker with bash
```bash
docker exec -it postgres_local_secure bash
root@253771de3f22:/# psql -U postgres -h localhost

psql (16.10 (Debian 16.10-1.pgdg13+1))
SSL connection (protocol: TLSv1.3, cipher: TLS_AES_256_GCM_SHA384, compression: off)
Type "help" for help.

postgres=# \l
```

#### tesing with python
The final step is to prove that the security is working. A connection attempt will only succeed if it is made from `localhost` and uses SSL.

Here is an example using a Python script with the `psycopg2` library.

1.  **Install the library:**
    ```bash
    pip install psycopg2-binary
    ```

2.  **Create and run a Python script (`test_pg_connection.py`):**
    ```python
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

    ```

When you run this script, a successful output confirms that your PostgreSQL instance is running, secure, and correctly configured to enforce encrypted connections. You have successfully completed the deployment.