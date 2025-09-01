Of course. Here is a complete guide to convert your `docker run` command for the vLLM Gemma-3 server into a robust, secure, and manageable Docker Compose setup.

This approach is highly recommended for long-running services as it provides automatic restarts, health monitoring, conflict-free networking, and secure management of your API key.

---

### **Robust Gemma-3 vLLM Server Deployment with Docker Compose**

**Objective:**
To launch the `vllm/vllm-openai` server for the `gemma-3-4b-it` model using Docker Compose. This guide enhances the basic command by adding a secure way to handle API keys, a conflict-free network, a health check, and an automatic restart policy.

**Key Improvements over `docker run`:**
*   **Secure API Key:** Your API key is stored in a separate `.env` file, not in the main configuration, preventing it from being accidentally committed to version control.
*   **Stability:** The server is configured to restart automatically if it crashes.
*   **Health Monitoring:** Docker will continuously check if the server is responsive and report its status.
*   **Conflict-Free Networking:** A custom network prevents IP address clashes with VPNs or other services.
*   **Easy Management:** Use simple `docker compose` commands to start, stop, and view logs.

**Prerequisites:**
1.  **Docker and Docker Compose are installed.**
2.  **NVIDIA Container Toolkit is installed** to allow Docker to use your GPUs.
3.  You are logged into any necessary container registries (like Docker Hub).

---

### **Step 1: Set Up the Project Directory and Secure API Key**

It's best practice to keep your configuration files organized in a dedicated directory.

1.  **Create a directory for your vLLM setup:**
    ```bash
    mkdir -p ~/gemma3-server
    ```

2.  **Navigate into that directory:**
    ```bash
    cd ~/gemma3-server
    ```

3.  **Create a `.env` file to securely store your API key:**
    This is the most important step for security. Docker Compose will automatically read variables from this file.
    ```bash
    # Create the file and add your API key.
    # Replace "MY KEY" with your actual secret key.
    echo "VLLM_API_KEY=MY KEY" > .env
    ```

4.  **(Crucial) Add the `.env` file to `.gitignore`:**
    If you are using Git, you must prevent your secrets file from ever being committed.
    ```bash
    echo ".env" >> .gitignore
    ```

---

### **Step 2: Create the `docker-compose.yml` File**

This single file replaces your long `docker run` command and adds all the robust features.

Create a new file named `docker-compose.yml` inside the `~/gemma3-server` directory. Copy and paste the entire block of code below into this file.

```yaml
# ~/gemma3-server/docker-compose.yml
# A robust, secure, and conflict-free setup for a vLLM OpenAI-compatible server.

version: '3.8'

services:
  vllm:
    image: vllm/vllm-openai:latest
    container_name: gemma3-server

    # --- Secure API Key and Model Configuration ---
    # The command is built using the variable from our .env file.
    # This keeps the secret out of the main configuration.
    command: >
      --model RedHatAI/gemma-3-4b-it-FP8-dynamic
      --host 0.0.0.0
      --port 8000
      --max-model-len 32768
      --gpu-memory-utilization 0.85
      --guided-decoding-backend xgrammar
      --trust-remote-code
      --api-key ${VLLM_API_KEY}

    # --- GPU Access ---
    # This is the equivalent of '--gpus all'
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

    # --- Data Persistence ---
    # Mounts the Hugging Face cache to speed up model downloads on subsequent runs.
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface

    # --- Port Mapping ---
    # Binds port 5000 on your host machine to port 8000 in the container.
    # The '127.0.0.1:' part makes it accessible only from your local machine for security.
    # Remove '127.0.0.1:' to expose it to your local network.
    ports:
      - "127.0.0.1:5000:8000"

    # --- Stability and Health Monitoring ---
    # Automatically restarts the container unless you manually stop it.
    restart: unless-stopped

    # Checks if the vLLM server is responsive.
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 15s
      retries: 5
      # Give the server 3 minutes to start and load the model before the first health check.
      start_period: 180s

    # --- Conflict-Free Networking ---
    # Connects this service to our custom network.
    networks:
      - vllm-net

# --- Custom Network Definition to Avoid Conflicts ---
networks:
  vllm-net:
    driver: bridge
    ipam:
      driver: default
      config:
        # We define a custom subnet that is very unlikely to conflict with a VPN.
        - subnet: "10.58.0.0/24"
```

---

### **Step 3: Launch and Manage Your vLLM Server**

You can now use simple `docker compose` commands to control your server.

1.  **Start the Server:**
    Make sure you are in the `~/gemma3-server` directory. The first time you run this, it will download the container image and the model, which can take a significant amount of time.
    ```bash
    docker compose up -d
    ```

2.  **Check the Status:**
    This command shows if the container is running and its health status.
    ```bash
    docker compose ps
    ```
    Initially, the status will be `(health: starting)`. After the `start_period` (3 minutes) and a successful check, it will change to `(healthy)`.

3.  **View Logs:**
    This is very useful for monitoring the model loading process and seeing any potential errors.
    ```bash
    docker compose logs -f
    ```
    (Press `Ctrl+C` to stop viewing the logs).

4.  **Stop the Server:**
    When you are finished, this command will cleanly stop and remove the container.
    ```bash
    docker compose down
    ```

---

### **Step 4: Verify the Service**

You can test the OpenAI-compatible endpoint using a `curl` command.

1.  **Open a new terminal** and run the following command.
2.  **Remember to replace `MY KEY`** with the same API key you put in your `.env` file.

    ```bash
    curl http://localhost:5000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer MY KEY" \
    -d '{
        "model": "RedHatAI/gemma-3-4b-it-FP8-dynamic",
        "messages": [
            {"role": "user", "content": "What is the capital of France?"}
        ]
    }'
    ```

If the setup is successful, you will receive a JSON response from the model with the answer. You now have a robust, secure, and easily manageable LLM inference server.