import chromadb
import uuid

CHROMA_PORT = 8443

print(f"Attempting to connect to insecure ChromaDB server on port {CHROMA_PORT}...")

try:
    # The client now connects to the new port.
    client = chromadb.HttpClient(host='localhost', port=CHROMA_PORT)

    # Verify the connection by calling the heartbeat method
    heartbeat = client.heartbeat()
    print(f"\n✅ Connection successful!")
    print(f"   Server heartbeat response (nanoseconds): {heartbeat}")

    # Perform a basic operation to confirm functionality
    collection_name = f"dev_test_{uuid.uuid4().hex}"
    collection = client.get_or_create_collection(name=collection_name)
    
    collection.add(
        documents=["This is a test of a connection on a custom port."],
        ids=["id1"]
    )
    
    results = collection.query(query_texts=["custom port test"], n_results=1)
    
    print(f"   Successfully created and queried collection '{collection_name}'.")
    print(f"   Query results: {results['documents'][0]}")
    
    # Clean up the test collection
    client.delete_collection(name=collection_name)
    print(f"   Successfully deleted test collection.")

except Exception as e:
    print(f"\n❌ An unexpected error occurred. Is the ChromaDB container running?")
    print(f"   Error: {e}")