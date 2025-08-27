import redis

print("Attempting to connect to insecure (development) Redis server...")

try:
    # Connection requires no password and no SSL/TLS parameters.
    r = redis.Redis(
        host='localhost',
        port=6379,
        decode_responses=True # Optional: makes responses strings instead of bytes
    )

    # Ping the server to confirm the connection is active
    response = r.ping()
    
    if response:
        print("\n✅ Connection successful!")
        
        # Perform a basic SET and GET to verify functionality
        r.set('dev_test', 'success')
        value = r.get('dev_test')
        
        print(f"   Server PING response: {response}")
        print(f"   Successfully SET and GET key 'dev_test' with value: '{value}'")
    else:
        print("\n❌ Connection appeared to succeed, but PING failed.")

except redis.exceptions.ConnectionError as e:
    print("\n❌ Connection failed. Check if the server is running and the port is correct.")
    print(f"   Error: {e}")
except Exception as e:
    print(f"\n❌ An unexpected error occurred: {e}")