import chromadb
import uuid

print("--- Attempting to connect to ChromaDB server at localhost:8443 ---")

try:
    # Connect to the ChromaDB server running on your local machine
    client = chromadb.HttpClient(host='localhost', port=8443)
    client.heartbeat()
    print("✅ Connection successful!")

    # --- Perform a full create-read-query-delete cycle ---
    collection_name = f"test_collection_{uuid.uuid4().hex}"
    print(f"\n--- Running test with collection: '{collection_name}' ---")

    collection = client.get_or_create_collection(name=collection_name)
    print("   - Step 1: Collection created successfully.")

    collection.add(
        documents=["This is a test document from a conflict-free setup."],
        ids=["id1"]
    )
    print("   - Step 2: Document added successfully.")

    results = collection.query(query_texts=["test document"], n_results=1)
    print("   - Step 3: Query executed successfully.")
    
    # Verify the result
    if "conflict-free setup" in results['documents'][0][0]:
            print("   - Step 4: Document content verified successfully.")
    else:
        raise ValueError("Query returned unexpected result.")

    # Clean up the test collection
    client.delete_collection(name=collection_name)
    print(f"   - Step 5: Test collection deleted successfully.")

    print("\n--- ✅ All operations completed successfully! Your ChromaDB instance is ready. ---")

except Exception as e:
    print(f"\n❌ An error occurred. Please check the following:")
    print("   1. Is the ChromaDB container running? Run 'sudo docker compose ps' to check.")
    print(f"   2. Error details: {e}")