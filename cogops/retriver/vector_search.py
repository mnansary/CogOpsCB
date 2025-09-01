import os
import yaml
import chromadb
import logging
import asyncio
from collections import defaultdict
from dotenv import load_dotenv
from typing import List, Dict, Optional, Any, Tuple

# Import your custom embedder module and its configuration
from cogops.models.jina_embedder import JinaTritonEmbedder, JinaV3TritonEmbedderConfig

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
load_dotenv()

class VectorRetriever:
    """
    A class to retrieve and rank documents from ChromaDB using Reciprocal Rank Fusion (RRF).
    This approach combines results from multiple collections based on their rank to
    produce a single, highly relevant list of candidate documents.
    """
    def __init__(self, config_path: str = "configs/config.yaml"):
        logging.info("Initializing VectorRetriever...")
        full_config = self._load_config(config_path)
        retriever_config = full_config.get("vector_retriever")
        if not retriever_config:
            raise ValueError(f"Config file '{config_path}' is missing 'vector_retriever' section.")

        self.top_k = retriever_config.get("top_k", 5)
        self.all_collection_names = retriever_config.get("collections", [])
        self.passage_collection_name = retriever_config.get("passage_collection")
        self.max_passages_to_rerank = retriever_config.get("max_passages_to_rerank", 10)
        self.rrf_k = retriever_config.get("rrf_k", 60)
        self.passage_id_key = retriever_config.get("passage_id_meta_key", "passage_id")

        if not self.all_collection_names or not self.passage_collection_name:
            raise ValueError("Config missing 'collections' or 'passage_collection' keys.")

        self.chroma_client = self._connect_to_chroma()
        self.embedder = self._initialize_embedder()

        self.passage_collection = self.chroma_client.get_collection(name=self.passage_collection_name)
        self.all_collections = {
            name: self.chroma_client.get_collection(name=name) for name in self.all_collection_names
        }
        logging.info(f"VectorRetriever initialized. Passage ID key: '{self.passage_id_key}'.")

    def _load_config(self, config_path: str) -> Dict:
        logging.info(f"Loading configuration from: {config_path}")
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logging.error(f"Configuration file not found at: {config_path}")
            raise

    def _connect_to_chroma(self) -> chromadb.HttpClient:
        CHROMA_HOST = os.environ.get("CHROMA_DB_HOST", "localhost")
        CHROMA_PORT = int(os.environ.get("CHROMA_DB_PORT", 8443))
        logging.info(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
        try:
            client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
            client.heartbeat()
            logging.info("✅ ChromaDB connection successful!")
            return client
        except Exception as e:
            logging.error(f"Failed to connect to ChromaDB: {e}", exc_info=True)
            raise

    def _initialize_embedder(self) -> JinaTritonEmbedder:
        TRITON_URL = os.environ.get("TRITON_EMBEDDER_URL", "http://localhost:6000")
        logging.info(f"Initializing embedder with Triton at: {TRITON_URL}")
        embedder_config = JinaV3TritonEmbedderConfig(triton_url=TRITON_URL)
        return JinaTritonEmbedder(config=embedder_config)

    async def _query_collection_async(
        self,
        collection_name: str,
        query_embedding: List[float],
        top_k: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[int, int]]:
        """
        Queries a single collection and returns a list of (passage_id, rank) tuples.
        Passage IDs are converted to integers for consistent matching.
        """
        collection = self.all_collections[collection_name]
        try:
            query_args = {
                "query_embeddings": [query_embedding],
                "n_results": top_k,
                "include": ["metadatas"]
            }
            if filters:
                query_args["where"] = filters
            
            results = collection.query(**query_args)
            
            ranked_results = []
            if results and results['metadatas'] and results['metadatas'][0]:
                for i, meta in enumerate(results['metadatas'][0]):
                    passage_id_val = meta.get(self.passage_id_key)
                    if passage_id_val is not None:
                        try:
                            # --- FIX: Ensure passage_id is an integer ---
                            passage_id = int(passage_id_val)
                            rank = i + 1
                            ranked_results.append((passage_id, rank))
                        except (ValueError, TypeError):
                            logging.warning(f"Could not convert passage_id '{passage_id_val}' to int. Skipping.")
                            continue
            return ranked_results
        except Exception as e:
            logging.error(f"Error querying {collection_name}: {e}")
            return []

    async def get_unique_passages_from_all_collections(
        self,
        query: str,
        top_k: int = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        if top_k is None:
            top_k = self.top_k

        log_message = f"Querying all collections for '{query}' with top_k={top_k} each for RRF."
        if filters:
            log_message += f" Applying filters: {filters}"
        logging.info(log_message)
        
        query_embedding = self.embedder.embed_queries([query])[0]

        tasks = [
            self._query_collection_async(name, query_embedding, top_k, filters)
            for name in self.all_collection_names
        ]
        list_of_ranked_lists = await asyncio.gather(*tasks)

        fused_scores = defaultdict(float)
        for ranked_list in list_of_ranked_lists:
            for passage_id, rank in ranked_list:
                fused_scores[passage_id] += 1.0 / (self.rrf_k + rank)
        
        if not fused_scores:
            logging.warning("No passages found after querying all collections.")
            return []

        # --- sorted_passage_ids will now be a list of integers ---
        sorted_passage_ids = sorted(
            fused_scores.keys(),
            key=lambda pid: fused_scores[pid],
            reverse=True
        )

        top_passage_ids = sorted_passage_ids[:self.max_passages_to_rerank]
        logging.info(f"Found {len(fused_scores)} unique passages. Retrieving top {len(top_passage_ids)} after RRF.")

        if not top_passage_ids:
            return []

        try:
            # --- FIX: The where clause now correctly uses integers ---
            retrieved_passages = self.passage_collection.get(
                where={self.passage_id_key: {"$in": top_passage_ids}}
            )
            
            passage_map = {
                # --- FIX: Convert the key from metadata to an int for matching ---
                int(meta[self.passage_id_key]): {
                    'id': retrieved_passages['ids'][i],
                    'document': retrieved_passages['documents'][i],
                    'metadata': meta
                }
                for i, meta in enumerate(retrieved_passages['metadatas'])
                if self.passage_id_key in meta
            }

        except Exception as e:
            logging.error(f"Failed to retrieve passages from ChromaDB for IDs: {top_passage_ids}. Error: {e}")
            return []

        # Re-order the results according to our RRF sort
        final_ordered_docs = []
        for passage_id in top_passage_ids:
            if passage_id in passage_map:
                final_ordered_docs.append(passage_map[passage_id])
        
        return final_ordered_docs

    def close(self):
        if self.embedder:
            self.embedder.close()
            logging.info("Embedder connection closed.")

async def main():
    try:
        retriever = VectorRetriever(config_path="configs/config.yaml")
        user_query = "হারিয়ে যাওয়া জাতীয় পরিচয়পত্র উত্তোলনের পদ্ধতি"
        
        print("\n--- Testing: Get Passages with Reciprocal Rank Fusion ---")
        passages = await retriever.get_unique_passages_from_all_collections(user_query,filters={"category":'স্মার্ট কার্ড ও জাতীয়পরিচয়পত্র'})
        
        print(f"\nRetrieved {len(passages)} passages, sorted by RRF score:")
        for i, passage in enumerate(passages):
            passage_id = passage['metadata'].get(retriever.passage_id_key, 'N/A')
            print(
                f"  Rank {i+1}: Passage ID: {passage_id}, "
                f"Content: '{passage['document'][:70]}...'"
            )
            
    except Exception as e:
        logging.error(f"An error occurred in the main execution: {e}", exc_info=True)
    finally:
        if 'retriever' in locals():
            retriever.close()
        logging.info("\n--- Script Finished ---")


if __name__ == "__main__":
    asyncio.run(main())