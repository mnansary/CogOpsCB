**FOR MODEL CREATION**: https://github.com/mnansary/Triton-Jina-v3-TRT


### **Robust Triton Inference Server Deployment with Docker Compose**

**Objective:**
To launch the NVIDIA Triton Inference Server using Docker Compose, adding a custom network to prevent conflicts, a health check to monitor its status, and an automatic restart policy for improved stability.

**Prerequisites:**
1.  **Docker and Docker Compose are installed.**
2.  **NVIDIA Container Toolkit is installed.** This is what allows Docker to access your GPUs (`--gpus all`).
3.  **Your model repository exists.** Based on your command, this guide assumes your models are located at `~/triton_repo`.

---

### **Step 1: Create a Project Directory**

It's best practice to keep your `docker-compose.yml` file in its own dedicated directory.

1.  **Create a directory for your Triton setup:**
    ```bash
    mkdir -p ~/triton-server
    ```
2.  **Navigate into that directory:**
    ```bash
    cd ~/triton-server
    ```
    You will create the `docker-compose.yml` file here. Your models will remain in `~/triton_repo`.

---

### **Step 2: Create the `docker-compose.yml` File**

This single file will replace your long `docker run` command and add the new features.

Create a new file named `docker-compose.yml` inside the `~/triton-server` directory. Copy and paste the entire block of code below into this file.

```yaml
# ~/triton-server/docker-compose.yml
# A robust, conflict-free setup for the Triton Inference Server.

version: '3.8'

services:
  triton:
    # --- Base Configuration (from your 'docker run' command) ---
    image: nvcr.io/nvidia/tritonserver:25.05-py3
    container_name: jinatriton
    # This command is passed to the container on startup
    command: tritonserver --model-repository=/models
    volumes:
      # Maps your local model repository into the container
      - ~/triton_repo:/models:ro # ':ro' makes the volume read-only for added safety
    ports:
      - "127.0.0.1:6000:8000" # HTTP
      - "127.0.0.1:6001:8001" # gRPC
      - "127.0.0.1:6002:8002" # Metrics
      # We bind to 127.0.0.1 (localhost) for security, preventing network exposure.
      # If you need to access it from other machines, change to "6000:8000", etc.

    # --- GPU Access ---
    # This is the Docker Compose equivalent of '--gpus all'
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

    # --- NEW: Stability and Health Monitoring ---
    # Automatic Restart Policy: Restarts the container unless you manually stop it.
    restart: unless-stopped

    # Health Check: Docker will periodically check if Triton is responsive.
    healthcheck:
      # Queries the standard Triton health endpoint.
      test: ["CMD", "curl", "-f", "http://localhost:8000/v2/health/ready"]
      interval: 15s      # Check every 15 seconds
      timeout: 10s       # Wait up to 10 seconds for a response
      retries: 5         # Try 5 times before marking as unhealthy
      start_period: 60s  # Give the server 60 seconds to start up before the first check

    # --- NEW: Conflict-Free Networking ---
    # Connects this service to our custom network defined below.
    networks:
      - triton-net

# --- Custom Network Definition to Avoid Conflicts ---
networks:
  triton-net:
    driver: bridge
    ipam:
      driver: default
      config:
        # We define a custom subnet that is very unlikely to conflict with VPNs or other networks.
        - subnet: "10.57.0.0/24"
```

---

### **Step 3: Launch and Manage Your Triton Server**

Now, you can use simple `docker compose` commands to manage your server.

1.  **Start the Triton Server:**
    Make sure you are in the `~/triton-server` directory. This command starts the server in the background (`-d`).
    ```bash
    docker compose up -d
    ```

2.  **Check the Status:**
    This command shows you if the container is running and healthy.
    ```bash
    docker compose ps
    ```
    Initially, the `STATUS` will show `(health: starting)`. After the `start_period` (60 seconds) and a successful check, it will change to `(healthy)`.

3.  **View Logs:**
    If you need to see the output from the Triton server (e.g., to see which models are loading), use this command:
    ```bash
    docker compose logs -f
    ```
    (Press `Ctrl+C` to stop viewing the logs).

4.  **Stop the Server:**
    When you are finished, you can stop and remove the container cleanly with a single command:
    ```bash
    docker compose down
    ```

You have now successfully converted your command into a more powerful and stable Docker Compose setup that is easy to manage and resilient to common network issues.