import chromadb
import uuid
import os

# Import your custom embedder classes from the file you created
from cogops.models.embGemma_embedder import GemmaTritonEmbedder, GemmaTritonEmbedderConfig

# --- Configuration ---
# You can modify these or set them as environment variables
TRITON_URL = os.environ.get("TRITON_EMBEDDER_URL", "http://localhost:6000")
CHROMA_HOST = os.environ.get("CHROMA_DB_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_DB_PORT", 8443))

print("--- Test Configuration ---")
print(f"   - ChromaDB Host: {CHROMA_HOST}")
print(f"   - ChromaDB Port: {CHROMA_PORT}")
print(f"   - Triton URL: {TRITON_URL}")
print("--------------------------\n")

try:
    # --- Step 1: Initialize the Custom Embedder ---
    print("--- Initializing Gemma Triton Embedder ---")
    embedder_config = GemmaTritonEmbedderConfig(triton_url=TRITON_URL)
    embedder = GemmaTritonEmbedder(config=embedder_config)
    
    # Get the embedding function in a format ChromaDB can use
    chroma_embedding_function = embedder.as_chroma_passage_embedder()
    print("✅ Embedder initialized successfully.")

    # --- Step 2: Connect to ChromaDB ---
    print(f"\n--- Attempting to connect to ChromaDB server at {CHROMA_HOST}:{CHROMA_PORT} ---")
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    client.heartbeat() # Check if the server is responsive
    print("✅ ChromaDB connection successful!")

    # --- Step 3: Perform a full create-read-query-delete cycle ---
    collection_name = f"test_collection_{uuid.uuid4().hex}"
    print(f"\n--- Running test with collection: '{collection_name}' ---")

    # Create the collection, passing in our custom embedding function
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=chroma_embedding_function
    )
    print("   - Step 1: Collection created with custom embedder successfully.")

    # Add a document. This will trigger the call to your Triton server.
    print("   - Step 2: Adding document (this will call the embedder)...")
    collection.add(
        documents=["This is a test document embedded by a Gemma model on Triton."],
        ids=["id1"]
    )
    print("   - Step 3: Document added successfully.")

    # Query the collection. This will also call the Triton server to embed the query text.
    print("   - Step 4: Executing query (this will also call the embedder)...")
    results = collection.query(query_texts=["Gemma model test"], n_results=1)
    print("   - Step 5: Query executed successfully.")
    
    # Verify the result
    if "embedded by a Gemma model" in results['documents'][0][0]:
        print("   - Step 6: Document content verified successfully.")
    else:
        print(f"   - ❌ Verification failed. Unexpected result: {results['documents'][0][0]}")
        raise ValueError("Query returned unexpected result.")

    # Clean up the test collection
    client.delete_collection(name=collection_name)
    print(f"   - Step 7: Test collection deleted successfully.")

    print("\n--- ✅ All operations completed successfully! Your ChromaDB and Triton integration is working. ---")

except Exception as e:
    print(f"\n❌ An error occurred. Please check the following:")
    print("   1. Is the ChromaDB container running? Run 'sudo docker compose ps' to check.")
    print("   2. Is the Triton Inference Server container running and accessible at the configured URL?")
    print(f"   3. Error details: {e}")

finally:
    if 'embedder' in locals():
        embedder.close()