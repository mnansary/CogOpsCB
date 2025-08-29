# test_chroma_search.py

import argparse
import logging
import os
import sys
import yaml
from dotenv import load_dotenv
import chromadb

# Import the same custom embedder modules used during ingestion
from cogops.models.jina_embedder import JinaTritonEmbedder, JinaV3TritonEmbedderConfig

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)

# --- Load Infrastructure Configuration from Environment ---
load_dotenv()
TRITON_URL = os.environ.get("TRITON_EMBEDDER_URL", "http://localhost:6000")
CHROMA_HOST = os.environ.get("CHROMA_DB_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_DB_PORT", 8443))

def load_config(config_path: str) -> dict:
    """Loads the YAML configuration file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            logging.info(f"Loading configuration from: {config_path}")
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"Configuration file not found at: {config_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error loading or parsing configuration file: {e}")
        sys.exit(1)

def initialize_embedder(triton_url: str) -> JinaTritonEmbedder:
    """Initializes the Jina Triton embedder."""
    logging.info(f"Initializing embedder with Triton at: {triton_url}")
    embedder_config = JinaV3TritonEmbedderConfig(triton_url=triton_url)
    return JinaTritonEmbedder(config=embedder_config)

def run_semantic_search(collection: chromadb.Collection, query_text: str, n_results: int = 3):
    """
    Constructs and executes a semantic search query against the collection
    and prints the formatted results.
    """
    # --- Print Query Information ---
    print("\n" + "="*80)
    print(f"Executing Query: '{query_text}'")
    print("="*80)

    try:
        # The core query operation in ChromaDB.
        # It takes the query text, embeds it using the collection's embedding function,
        # and finds the 'n_results' most similar documents.
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
            include=["metadatas", "documents", "distances"] # Ask for all useful info
        )

        # The result structure is a dictionary of lists of lists.
        # We access the first list [0] because we only sent one query.
        documents = results['documents'][0]
        metadatas = results['metadatas'][0]
        distances = results['distances'][0]

        if not documents:
            print("--- No results found. ---")
            return

        print(f"Showing top {len(documents)} semantic search results:\n")
        for i in range(len(documents)):
            distance = distances[i]
            doc_content = documents[i]
            metadata = metadatas[i]

            print(f"  Result {i+1} | Distance: {distance:.4f} (Lower is better)")
            print(f"  Text: {doc_content}")
            print(f"  Metadata: {metadata}\n")

    except Exception as e:
        logging.error(f"An error occurred during search: {e}", exc_info=True)


def main():
    """Main entry point for the test script."""
    parser = argparse.ArgumentParser(
        description="Test semantic search queries against a ChromaDB collection."
    )
    parser.add_argument(
        '--config',
        type=str,
        required=True,
        help="Path to the chroma_ingestion_config.yaml file."
    )
    args = parser.parse_args()

    config = load_config(args.config)
    collection_name = config['collection_name']
    embedder = None  # Initialize embedder to None

    try:
        # --- Connect to Services ---
        logging.info(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}")
        chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        chroma_client.heartbeat() # Verify connection
        logging.info("✅ ChromaDB connection successful!")
        
        # We must initialize the embedder to define the embedding function for the collection
        embedder = initialize_embedder(TRITON_URL)
        passage_embedding_function = embedder.as_chroma_passage_embedder()

        # Get the existing collection. This script assumes ingestion is already done.
        logging.info(f"Accessing existing collection: '{collection_name}'")
        collection = chroma_client.get_collection(
            name=collection_name,
            embedding_function=passage_embedding_function
        )
        logging.info(f"Successfully connected to collection with {collection.count()} documents.")

        # --- Define Query Variations ---
        test_queries = {
            "✅ Vanilla Query": "এন আই ডি কার্ড করার প্রক্রিয়া কি?",
            "✅ Personal Query": "আমার চাচা অসুস্থ, আমি রাজশাহীতে আছি। জরুরি অ্যাম্বুলেন্সের নাম্বার লাগবে।",
            "❌ Non-Service Query": "আজকে আমার দিনটা খুব খারাপ গেলো",
            "⚠️ Ambiguous Query": "আমি ফর্ম পূরণ করতে চাই",
            "✅ Compound Query": "আমি পাসপোর্ট বানানোর নিয়ম জানতে চাই আর অফিসের ঠিকানা কোথায়?",
            "✅ Mixed-Language Query": "How to get birth certificate online?"
        }

        # --- Run Tests ---
        for category, query in test_queries.items():
            print(f"\n\n{'='*20} Testing Category: {category} {'='*20}")
            run_semantic_search(collection, query, n_results=3)

    except ValueError as e:
        # This error is often raised by ChromaDB if the collection doesn't exist.
        logging.error(f"Could not find collection '{collection_name}'. Please run the ingestion script first. Details: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        if embedder:
            embedder.close() # Important to close the connection to Triton
            logging.info("Embedder connection closed.")
        logging.info("--- Search Test Script Finished ---")

if __name__ == "__main__":
    main()