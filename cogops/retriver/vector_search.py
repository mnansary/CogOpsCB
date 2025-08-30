import os
import yaml
import chromadb
import logging
import asyncio
from dotenv import load_dotenv
from typing import List, Dict, Set, Optional, Any

# Import your custom embedder module and its configuration
from cogops.models.jina_embedder import JinaTritonEmbedder, JinaV3TritonEmbedderConfig

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
load_dotenv()

class VectorRetriever:
    """
    A class to retrieve relevant documents from ChromaDB collections.
    Now supports optional metadata filtering.
    """
    def __init__(self, config_path: str = "configs/config.yaml"):
        """
        Initializes the VectorRetriever by loading configuration, setting up
        the embedder, and connecting to the ChromaDB client.
        """
        logging.info("Initializing VectorRetriever...")
        # Load the entire config first, then extract the 'vector_retriever' section.
        full_config = self._load_config(config_path)
        retriever_config = full_config.get("vector_retriever")
        if not retriever_config:
            raise ValueError(f"Configuration file at '{config_path}' is missing the 'vector_retriever' section.")

        # Now, use the specific config for this class.
        self.top_k = retriever_config.get("top_k", 3)
        self.all_collection_names = retriever_config.get("collections", [])
        self.passage_collection_name = retriever_config.get("passage_collection") # No default, should be specified
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

    
    # --- MODIFIED METHOD (Step 2) ---
    async def _query_collection_async(
        self,
        collection_name: str,
        query_embedding: List[float],
        top_k: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[int]:
        """Helper to query a single collection asynchronously and return passage_ids."""
        collection = self.all_collections[collection_name]
        try:
            # Build the arguments for the query
            query_args = {
                "query_embeddings": [query_embedding],
                "n_results": top_k
            }
            # If filters are provided, add them to the 'where' clause
            if filters:
                query_args["where"] = filters
            
            results = collection.query(**query_args)
            
            passage_ids = [meta['passage_id'] for meta in results['metadatas'][0] if 'passage_id' in meta]
            return passage_ids
        except Exception as e:
            logging.error(f"Error querying {collection_name}: {e}")
            return []

    # --- MODIFIED METHOD (Step 1) ---
    async def get_unique_passages_from_all_collections(
        self,
        query: str,
        top_k: int = None,
        filters: Optional[Dict[str, Any]] = None  # <-- NEW PARAMETER
    ) -> List[Dict]:
        """
        Gets unique passages by combining results from all collections.
        Applies an optional metadata filter during the search.
        """
        if top_k is None:
            top_k = self.top_k

        log_message = f"Querying all collections for '{query}' with top_k={top_k} each."
        if filters:
            log_message += f" Applying filters: {filters}"
        logging.info(log_message)
        
        # 1. Embed the query once
        query_embedding = self.embedder.embed_queries([query])[0]

        # 2. Create and run async query tasks, passing the filters down
        tasks = [
            self._query_collection_async(name, query_embedding, top_k, filters) # <-- Pass filters
            for name in self.all_collection_names
        ]
        results_from_collections = await asyncio.gather(*tasks)

        # 3. Collect all unique passage_ids
        unique_passage_ids: Set[int] = set()
        for passage_id_list in results_from_collections:
            unique_passage_ids.update(passage_id_list)
        
        logging.info(f"Found {len(unique_passage_ids)} unique passage IDs from all collections.")

        if not unique_passage_ids:
            return []

        # 4. Retrieve the full passage documents for the unique IDs
        unique_ids_list = list(unique_passage_ids)
        retrieved_passages = self.passage_collection.get(
            where={"passage_id": {"$in": unique_ids_list}}
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

# --- MODIFIED EXAMPLE USAGE ---
async def main():
    """Main function to demonstrate the VectorRetriever with filtering."""
    try:
        retriever = VectorRetriever(config_path="configs/config.yaml")
        
        user_query = "হারিয়ে যাওয়া জাতীয় পরিচয়পত্র উত্তোলনের পদ্ধতি"

        # --- Example 1: Search WITHOUT a filter ---
        print("\n--- 1. Testing: Get Unique Passages (No Filter) ---")
        unique_passages_unfiltered = await retriever.get_unique_passages_from_all_collections(user_query)
        print(f"Found {len(unique_passages_unfiltered)} unique passages from combined search:")
        for passage in unique_passages_unfiltered: # Print first 2 for brevity
            print(f"  - ID: {passage['id']}, Metadata: {passage['metadata']}")

        print("\n" + "="*50 + "\n")

        # --- Example 2: Search WITH a filter ---
        print("--- 2. Testing: Get Unique Passages (With Filter) ---")
        
        # This is the filter dictionary. The key is the metadata field name.
        filter_dict = {"category": 'স্মার্ট কার্ড ও জাতীয়পরিচয়পত্র'}
        
        unique_passages_filtered = await retriever.get_unique_passages_from_all_collections(
            user_query,
            filters=filter_dict
        )
        print(f"Found {len(unique_passages_filtered)} unique passages from filtered search:")
        for passage in unique_passages_filtered:
            print(f"  - ID: {passage['id']}")
            print(f"    Passage: {passage['document'][:100]}...")
            print(f"    Metadata: {passage['metadata']}") # You should see the correct category here

    except Exception as e:
        logging.error(f"An error occurred in the main execution: {e}", exc_info=True)
    finally:
        if 'retriever' in locals():
            retriever.close()
        logging.info("\n--- Script Finished ---")


if __name__ == "__main__":
    # To run the async main function
    asyncio.run(main())