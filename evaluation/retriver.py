import os
import yaml
import chromadb
import logging
import asyncio
from collections import defaultdict
from dotenv import load_dotenv
from typing import List, Dict, Any, Tuple

# --- Custom Module Imports ---
# Make sure these paths are correct for your project structure
from cogops.models.embGemma_embedder import GemmaTritonEmbedder, GemmaTritonEmbedderConfig
from cogops.retriver.db import SQLDatabaseManager
from cogops.utils.db_config import get_postgres_config

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
load_dotenv()
POSTGRES_CONFIG = get_postgres_config()

# --- HARDCODED CONFIGURATION ---
CONFIG = {
    "top_k": 10,  # Number of initial candidates to retrieve from each ChromaDB collection.
    "max_passages_to_select": 3,  # Final number of passages to return after RRF fusion.
    "rrf_k": 60,  # Reciprocal Rank Fusion constant.
    "passage_id_meta_key": "passage_id"
}

class DynamicVectorRetriever:
    """
    Retrieves and ranks documents from multiple vector collections based on a dynamic
    model string that specifies which query pipelines to use. The results are fused
    using RRF, and the final passages are fetched from PostgreSQL.
    """
    def __init__(self):
        logging.info("Initializing DynamicVectorRetriever...")
        
        # --- Load hardcoded configuration ---
        self.top_k = CONFIG["top_k"]
        self.max_passages_to_select = CONFIG["max_passages_to_select"]
        self.rrf_k = CONFIG["rrf_k"]
        self.passage_id_key = CONFIG["passage_id_meta_key"]
        
        # --- Mapping from model string parts to query keys and collection names ---
        self.PIPELINE_MAP = {
            'prop': {
                'query_key': 'proposition',
                'collection_name': 'PropositionsDB'
            },
            'summ': {
                'query_key': 'summary',
                'collection_name': 'SummariesDB'
            },
            'ques': {
                'query_key': 'question',
                'collection_name': 'QuestionsDB'
            }
        }
        self.collection_names = [p['collection_name'] for p in self.PIPELINE_MAP.values()]

        # --- Initialize clients and embedder ---
        self.chroma_client = self._connect_to_chroma()
        self.db_manager = SQLDatabaseManager(POSTGRES_CONFIG)
        self.embedder = self._initialize_embedder()

        # Get handles to all required ChromaDB collections
        self.collections = {
            name: self.chroma_client.get_collection(name=name) for name in self.collection_names
        }
        logging.info(f"DynamicVectorRetriever initialized. Will select top {self.max_passages_to_select} passages after RRF.")

    def _connect_to_chroma(self) -> chromadb.HttpClient:
        CHROMA_HOST = os.environ.get("CHROMA_DB_HOST", "localhost")
        CHROMA_PORT = int(os.environ.get("CHROMA_DB_PORT", 8000))
        logging.info(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
        try:
            client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
            client.heartbeat()
            logging.info("✅ ChromaDB connection successful!")
            return client
        except Exception as e:
            logging.error(f"Failed to connect to ChromaDB: {e}", exc_info=True)
            raise

    def _initialize_embedder(self) -> GemmaTritonEmbedder:
        TRITON_URL = os.environ.get("TRITON_EMBEDDER_URL", "http://localhost:6000")
        logging.info(f"Initializing GemmaTritonEmbedder with Triton at: {TRITON_URL}")
        embedder_config = GemmaTritonEmbedderConfig(triton_url=TRITON_URL)
        return GemmaTritonEmbedder(config=embedder_config)

    async def _query_collection_async(
        self,
        collection_name: str,
        query_embedding: List[float],
        top_k: int
    ) -> List[Tuple[int, int]]:
        """Queries a single collection and returns a list of (passage_id, rank) tuples."""
        collection = self.collections[collection_name]
        try:
            results = collection.query(query_embeddings=[query_embedding], n_results=top_k, include=["metadatas"])
            ranked_results = []
            if results and results.get('metadatas') and results['metadatas'][0]:
                for i, meta in enumerate(results['metadatas'][0]):
                    passage_id_val = meta.get(self.passage_id_key)
                    if passage_id_val is not None:
                        try:
                            passage_id = int(passage_id_val)
                            rank = i + 1
                            ranked_results.append((passage_id, rank))
                        except (ValueError, TypeError):
                            logging.warning(f"Could not convert passage_id '{passage_id_val}' to int in '{collection_name}'. Skipping.")
            return ranked_results
        except Exception as e:
            logging.error(f"Error querying {collection_name}: {e}", exc_info=True)
            return []

    async def retrieve_passages(
        self,
        query_dict: Dict[str, str],
        model: str
    ) -> List[Dict[str, Any]]:
        """
        Performs the end-to-end retrieval process based on the model string.
        Throws a ValueError if the query_dict is missing keys required by the model.
        """
        logging.info(f"Starting retrieval for model '{model}' with queries: {list(query_dict.keys())}")
        
        # --- Step 1: Validate inputs and prepare queries for embedding ---
        active_pipelines = model.split('_')[1:]
        queries_to_embed = []
        task_metadata = []

        for pipe in active_pipelines:
            mapping = self.PIPELINE_MAP.get(pipe)
            if not mapping:
                raise ValueError(f"Invalid pipeline part '{pipe}' found in model name '{model}'.")

            query_key = mapping['query_key']
            collection_name = mapping['collection_name']
            
            # --- STRICT VALIDATION: Throw exception if key is missing ---
            if query_key not in query_dict:
                raise ValueError(f"Query key '{query_key}' is required by model '{model}' but was not found in the provided query_dict.")
            
            queries_to_embed.append(query_dict[query_key])
            task_metadata.append({'collection_name': collection_name})
        
        # --- Step 2: Batch embed all necessary queries ---
        all_embeddings = self.embedder.embed_queries(queries_to_embed)

        # --- Step 3: Create and run async query tasks in parallel ---
        tasks = []
        for i, meta in enumerate(task_metadata):
            embedding = all_embeddings[i]
            task = self._query_collection_async(meta['collection_name'], embedding, self.top_k)
            tasks.append(task)
        
        list_of_ranked_lists = await asyncio.gather(*tasks)

        # --- Step 4: Apply Reciprocal Rank Fusion ---
        fused_scores = defaultdict(float)
        for ranked_list in list_of_ranked_lists:
            for passage_id, rank in ranked_list:
                fused_scores[passage_id] += 1.0 / (self.rrf_k + rank)
        
        if not fused_scores:
            logging.warning("No passages found after querying all vector collections.")
            return []

        # --- Step 5: Sort by RRF score and select the top passage IDs ---
        sorted_passage_ids = sorted(fused_scores.keys(), key=lambda pid: fused_scores[pid], reverse=True)
        top_passage_ids = sorted_passage_ids[:self.max_passages_to_select]
        logging.info(f"RRF found {len(fused_scores)} unique passages. Selecting top {len(top_passage_ids)} IDs for retrieval.")

        if not top_passage_ids:
            return []

        # --- Step 6: Fetch full passage data from PostgreSQL ---
        try:
            logging.info(f"Fetching full data for IDs from PostgreSQL: {top_passage_ids}")
            passages_df = self.db_manager.select_passages_by_ids(top_passage_ids)
            
            if passages_df.empty:
                logging.warning(f"PostgreSQL query returned no data for IDs: {top_passage_ids}")
                return []

            passage_map = {row['passage_id']: row.to_dict() for index, row in passages_df.iterrows()}
            
            # --- Step 7: Format final output ---
            final_ordered_passages = []
            for pid in top_passage_ids:
                passage_data = passage_map.get(pid)
                if passage_data:
                    final_ordered_passages.append({
                        "passage_id": passage_data.get('passage_id'),
                        "passage_text": passage_data.get('text')
                    })
            
            return final_ordered_passages

        except Exception as e:
            logging.error(f"Failed to retrieve passages from PostgreSQL. Error: {e}", exc_info=True)
            return []

    def close(self):
        """Cleanly closes any open connections."""
        if self.embedder:
            self.embedder.close()
            logging.info("Embedder connection closed.")

async def main():
    """Main function to test the DynamicVectorRetriever with all specified cases."""
    retriever = None
    try:
        retriever = DynamicVectorRetriever()
        
        # --- Define sample queries ---
        prop_query = "জাতীয় পরিচয়পত্র হারিয়ে গেলে করণীয়"
        summ_query = "এনআইডি কার্ড রিইস্যু করার প্রক্রিয়া"
        ques_query = "এনআইডি কার্ড হারালে কী করতে হবে?"

        # --- Define test cases ---
        test_cases = [
            # Single Pipeline Cases
            {"name": "Proposition Only", "model": "embGemma_prop", "query_dict": {"proposition": prop_query}},
            {"name": "Summary Only", "model": "embGemma_summ", "query_dict": {"summary": summ_query}},
            {"name": "Question Only", "model": "embGemma_ques", "query_dict": {"question": ques_query}},
            
            # Two Pipeline Cases
            {"name": "Question + Proposition", "model": "embGemma_ques_prop", "query_dict": {"question": ques_query, "proposition": prop_query}},
            {"name": "Question + Summary", "model": "embGemma_ques_summ", "query_dict": {"question": ques_query, "summary": summ_query}},
            {"name": "Proposition + Summary", "model": "embGemma_prop_summ", "query_dict": {"proposition": prop_query, "summary": summ_query}},
            
            # Full Pipeline Case
            {"name": "Proposition + Summary + Question", "model": "embGemma_prop_summ_ques", "query_dict": {"proposition": prop_query, "summary": summ_query, "question": ques_query}},
            
            # Exception Test Case: Missing key in query_dict
            {"name": "Exception Test (Missing 'summary' key)", "model": "embGemma_prop_summ_ques", "query_dict": {"proposition": prop_query, "question": ques_query}},
        ]

        # --- Run all test cases ---
        for test in test_cases:
            print("\n" + "="*50)
            print(f"RUNNING TEST: {test['name']}")
            print(f"MODEL: {test['model']}")
            print(f"QUERIES: {test['query_dict']}")
            print("="*50)
            
            try:
                passages = await retriever.retrieve_passages(model=test['model'], query_dict=test['query_dict'])
                
                if passages:
                    print(f"\n✅ Retrieved {len(passages)} passages, sorted by relevance:")
                    for i, passage in enumerate(passages):
                        print("-" * 20)
                        print(f"Rank {i+1}:")
                        print(f"  Passage ID: {passage.get('passage_id')}")
                        print(f"  Passage Text: '{str(passage.get('passage_text'))[:150]}...'")
                else:
                    print("\n⚠️ No passages were retrieved for this test case.")
            
            except ValueError as e:
                # This block will now catch the expected exception for the specific test case
                print(f"\n✅ SUCCESS: Caught expected exception as required.")
                print(f"   ERROR: {e}")

            
    except Exception as e:
        logging.error(f"An error occurred in the main execution: {e}", exc_info=True)
    finally:
        if retriever:
            retriever.close()
        logging.info("\n\n--- All Tests Finished ---")

if __name__ == "__main__":
    asyncio.run(main())