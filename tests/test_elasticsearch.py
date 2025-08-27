from elasticsearch import Elasticsearch

print("Attempting to connect to insecure Elasticsearch server...")

try:
    # Client connects to 'http' and requires no authentication or certificates.
    client = Elasticsearch("http://localhost:9200")

    # Ping the cluster to verify the connection is active
    if client.ping():
        print("\n✅ Connection successful!")
        
        # Get and print basic cluster info
        info = client.info()
        print(f"   Cluster Name: {info['cluster_name']}")
        print(f"   Elasticsearch Version: {info['version']['number']}")
    else:
        print("\n❌ Connection failed. The ping was unsuccessful. Check container status.")

except Exception as e:
    print(f"\n❌ An unexpected error occurred: {e}")