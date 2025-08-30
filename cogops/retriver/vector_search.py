import os
import yaml
import chromadb
import logging
import asyncio
from dotenv import load_dotenv
from typing import List, Dict, Set

# Import your custom embedder module and its configuration
from cogops.models.jina_embedder import JinaTritonEmbedder, JinaV3TritonEmbedderConfig

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
load_dotenv()

class VectorRetriever:
    """
    A class to retrieve relevant documents from ChromaDB collections.
    """
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initializes the VectorRetriever by loading configuration, setting up
        the embedder, and connecting to the ChromaDB client.

        Args:
            config_path (str): The path to the YAML configuration file.
        """
        logging.info("Initializing VectorRetriever...")
        self.config = self._load_config(config_path)
        
        # --- Configuration Attributes ---
        self.top_k = self.config.get("top_k", 3)
        self.all_collection_names = self.config.get("collections", [])
        self.passage_collection_name = self.config.get("passage_collection", "PassageDB")

        if not self.all_collection_names or not self.passage_collection_name:
            raise ValueError("Configuration missing 'collections' or 'passage_collection' keys.")

        # --- Infrastructure Connections ---
        self.chroma_client = self._connect_to_chroma()
        self.embedder = self._initialize_embedder()

        # Get collection objects
        self.passage_collection = self.chroma_client.get_collection(name=self.passage_collection_name)
        self.all_collections = {
            name: self.chroma_client.get_collection(name=name) for name in self.all_collection_names
        }
        logging.info("VectorRetriever initialized successfully.")

    def _load_config(self, config_path: str) -> Dict:
        """Loads the YAML configuration file."""
        logging.info(f"Loading configuration from: {config_path}")
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logging.info("Configuration loaded successfully.")
            return config
        except FileNotFoundError:
            logging.error(f"Configuration file not found at: {config_path}")
            raise

    def _connect_to_chroma(self) -> chromadb.HttpClient:
        """Connects to the ChromaDB server."""
        CHROMA_HOST = os.environ.get("CHROMA_DB_HOST", "localhost")
        CHROMA_PORT = int(os.environ.get("CHROMA_DB_PORT", 8443))
        logging.info(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
        try:
            client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
            client.heartbeat() # Check connection
            logging.info("✅ ChromaDB connection successful!")
            return client
        except Exception as e:
            logging.error(f"Failed to connect to ChromaDB: {e}", exc_info=True)
            raise

    def _initialize_embedder(self) -> JinaTritonEmbedder:
        """Initializes the Jina Triton embedder for encoding queries."""
        TRITON_URL = os.environ.get("TRITON_EMBEDDER_URL", "http://localhost:6000")
        logging.info(f"Initializing embedder with Triton at: {TRITON_URL}")
        embedder_config = JinaV3TritonEmbedderConfig(triton_url=TRITON_URL)
        return JinaTritonEmbedder(config=embedder_config)

    def get_related_passages(self, query: str, top_k: int = None) -> List[Dict]:
        """
        Gets related passages by searching the primary passage collection.

        Args:
            query (str): The user query to search for.
            top_k (int, optional): The number of results to return. Defaults to config value.

        Returns:
            List[Dict]: A list of dictionaries containing the retrieved documents and their metadata.
        """
        if top_k is None:
            top_k = self.top_k
            
        logging.info(f"Querying collection '{self.passage_collection_name}' for '{query}' with top_k={top_k}")
        
        # Note: The query needs to be embedded. ChromaDB does this automatically
        # if the collection was created with an embedding function. However, for direct
        # query, we must provide the embedding.
        query_embedding = self.embedder.embed_queries([query])[0]

        results = self.passage_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )
        
        # Structure the results nicely
        retrieved_docs = []
        if results and results['ids'][0]:
            for i, doc_id in enumerate(results['ids'][0]):
                retrieved_docs.append({
                    'id': doc_id,
                    'document': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i]
                })
        return retrieved_docs

    async def _query_collection_async(self, collection_name: str, query_embedding: List[float], top_k: int) -> List[str]:
        """Helper to query a single collection asynchronously and return passage_ids."""
        collection = self.all_collections[collection_name]
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
            # Extract passage_id from metadata
            passage_ids = [meta['passage_id'] for meta in results['metadatas'][0] if 'passage_id' in meta]
            return passage_ids
        except Exception as e:
            logging.error(f"Error querying {collection_name}: {e}")
            return []

    async def get_unique_passages_from_all_collections(self, query: str, top_k: int = None) -> List[Dict]:
        """
        Gets unique passages by combining results from all collections using parallel async calls.

        Args:
            query (str): The user query to search for.
            top_k (int, optional): The number of results to fetch from *each* collection. Defaults to config.

        Returns:
            List[Dict]: A list of unique passages from the main passage collection.
        """
        if top_k is None:
            top_k = self.top_k

        logging.info(f"Querying all collections for '{query}' with top_k={top_k} each.")
        
        # 1. Embed the query once
        query_embedding = self.embedder.embed_queries([query])[0]

        # 2. Create and run async query tasks for all collections
        tasks = [
            self._query_collection_async(name, query_embedding, top_k)
            for name in self.all_collection_names
        ]
        results_from_collections = await asyncio.gather(*tasks)

        # 3. Collect all unique passage_ids
        unique_passage_ids: Set[str] = set()
        for passage_id_list in results_from_collections:
            unique_passage_ids.update(passage_id_list)
        
        logging.info(f"Found {len(unique_passage_ids)} unique passage IDs from all collections.")

        if not unique_passage_ids:
            return []

        # 4. Retrieve the full passage documents for the unique IDs
        # The 'where' clause is not ideal for large ID lists, 'get' is better.
        retrieved_passages = self.passage_collection.get(
            ids=list(unique_passage_ids)
        )
        
        # Structure the final output
        final_docs = []
        for i, doc_id in enumerate(retrieved_passages['ids']):
            final_docs.append({
                'id': doc_id,
                'document': retrieved_passages['documents'][i],
                'metadata': retrieved_passages['metadatas'][i]
            })

        return final_docs

    def close(self):
        """Closes the embedder connection."""
        if self.embedder:
            self.embedder.close()
            logging.info("Embedder connection closed.")

# --- Example Usage ---
async def main():
    """Main function to demonstrate the VectorRetriever."""
    try:
        retriever = VectorRetriever(config_path="configs/config.yaml")
        
        user_query = "হারিয়ে যাওয়া জাতীয় পরিচয়পত্র উত্তোলনের পদ্ধতি"

        print("\n--- 1. Testing: Get Related Passages from a Single Collection ---")
        related_passages = retriever.get_related_passages(user_query)
        print(f"Found {len(related_passages)} related passages:")
        for passage in related_passages:
            print(f"  - ID: {passage['id']}, Distance: {passage['distance']:.4f}")
            print(f"    Passage: {passage['document'][:100]}...") # Print first 100 chars
            print(f"    Metadata: {passage['metadata']}")
        
        print("\n" + "="*50 + "\n")

        print("--- 2. Testing: Get Unique Passages from All Collections (Async) ---")
        unique_passages = await retriever.get_unique_passages_from_all_collections(user_query)
        print(f"Found {len(unique_passages)} unique passages from combined search:")
        for passage in unique_passages:
            print(f"  - ID: {passage['id']}")
            print(f"    Passage: {passage['document'][:100]}...")
            print(f"    Metadata: {passage['metadata']}")

    except Exception as e:
        logging.error(f"An error occurred in the main execution: {e}", exc_info=True)
    finally:
        if 'retriever' in locals():
            retriever.close()
        logging.info("\n--- Script Finished ---")


if __name__ == "__main__":
    # To run the async main function
    asyncio.run(main())