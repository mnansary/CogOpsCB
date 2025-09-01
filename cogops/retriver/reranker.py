import os
import yaml
import asyncio
import logging
from typing import List, Dict, Any, Literal, Optional, Tuple

# Pydantic is used for structured data validation
from pydantic import BaseModel

# --- Core Component Imports ---
from cogops.models.gemma3_llm_async import AsyncLLMService, ContextLengthExceededError
from cogops.utils.token_manager import TokenManager

# --- Main Prompt Template ---
# MODIFIED: Added {search_query} for more precise context.
RERANK_PROMPT_TEMPLATE = """
You are an expert relevance evaluation assistant. Your task is to determine if the provided PASSAGE is relevant for answering the user's intent, considering the CONVERSATION HISTORY and the specific SEARCH QUERY used for retrieval.

Your evaluation must result in a score of 1, 2, or 3.
1: The passage directly and completely answers the user's query and provides additional context. 
2: The passage is on-topic and partially relevant, but not a complete answer. 
3: The passage is unrelated to the user's query.

CONVERSATION HISTORY:
{history_str}

USER QUERY (Natural Language):
{user_query}

SEARCH QUERY (Used for Retrieval):
{search_query}

PASSAGE TO EVALUATE:
{passage_text}
---
Based on all the information above, provide your relevance score and a brief justification.
"""

# --- Data Models ---
class RerankedPassage(BaseModel):
    """Represents a passage after it has been scored by the reranker."""
    passage_id: str
    score: Literal[1, 2, 3]
    reasoning: str
    document: str
    metadata: Optional[Dict[str, Any]] = None

class _SinglePassageScore(BaseModel):
    score: Literal[1, 2, 3]
    reasoning: str


class ParallelReranker:
    """
    Scores a list of passages in parallel using an LLM to determine relevance.
    Uses a semaphore for concurrency control and a token manager for safety.
    """
    def __init__(self, llm_service: AsyncLLMService, semaphore: asyncio.Semaphore, token_manager: TokenManager, passage_id_key: str):
        self.llm_service = llm_service
        self.semaphore = semaphore
        self.token_manager = token_manager
        self.passage_id_key = passage_id_key
        print("✅ ParallelReranker initialized with concurrency control and token management.")

    async def _score_one_passage(
        self,
        passage: Dict[str, Any],
        history: List[Tuple[str, str]],
        user_query: str,
        search_query: str, # <-- MODIFIED: Accept search_query
        **llm_kwargs: Any
    ) -> RerankedPassage | None:
        """Helper coroutine to score a single passage, handling token limits and errors."""
        
        prompt = self.token_manager.build_safe_prompt(
            template=RERANK_PROMPT_TEMPLATE,
            max_tokens=self.llm_service.max_context_tokens,
            history=history, # Pass raw history list to token manager
            user_query=user_query,
            search_query=search_query, # <-- MODIFIED: Pass search_query
            passage_text=passage['document']
        )

        async with self.semaphore:
            try:
                structured_response = await self.llm_service.invoke_structured(
                    prompt, _SinglePassageScore, **llm_kwargs
                )
                
                passage_metadata = passage.get('metadata', {})
                correct_passage_id = str(passage_metadata.get(self.passage_id_key, passage['id']))
                
                return RerankedPassage(
                    passage_id=correct_passage_id,
                    document=passage['document'],
                    score=structured_response.score,
                    reasoning=structured_response.reasoning,
                    metadata=passage_metadata
                )
            except ContextLengthExceededError:
                logging.warning(f"Passage {passage['id']} was too long to be scored. Assigning lowest relevance.")
                passage_metadata = passage.get('metadata', {})
                correct_passage_id = str(passage_metadata.get(self.passage_id_key, passage['id']))
                return RerankedPassage(
                    passage_id=correct_passage_id,
                    document=passage['document'],
                    score=3,
                    reasoning="The passage content was too long to fit into the model's context window for evaluation.",
                    metadata=passage_metadata
                )
            except Exception as e:
                logging.error(f"Could not score passage {passage['id']}. Error: {e}")
                return None

    async def rerank(
        self,
        conversation_history: List[Tuple[str, str]],
        user_query: str,
        search_query: str, # <-- MODIFIED: Accept search_query
        passages: List[Dict[str, Any]],
        **llm_kwargs: Any
    ) -> List[RerankedPassage]:
        """
        Reranks a list of passages using parallel LLM calls.
        """
        if not passages:
            return []
            
        logging.info(f"Reranking {len(passages)} passages in parallel...")
        
        tasks = [
            self._score_one_passage(p, conversation_history, user_query, search_query, **llm_kwargs)
            for p in passages
        ]
        
        results = await asyncio.gather(*tasks)
        
        successful_results = [res for res in results if res is not None]
        
        return successful_results

# --- Example Usage ---
if __name__ == '__main__':
    from dotenv import load_dotenv
    from cogops.retriver.vector_search import VectorRetriever

    async def main():
        print("--- Setting up dependencies for demonstration ---")
        load_dotenv()
        
        with open("configs/config.yaml", 'r') as f:
            config = yaml.safe_load(f)

        retriever = VectorRetriever(config_path="configs/config.yaml")
        
        reranker_cfg_name = config['task_to_model_mapping']['reranker']
        llm_cfg = config['llm_services'][reranker_cfg_name]
        token_cfg = config['token_management']

        api_key = os.getenv(llm_cfg['api_key_env'])
        model_name = os.getenv(llm_cfg['model_name_env'])
        base_url = os.getenv(llm_cfg['base_url_env'])

        llm_service = AsyncLLMService(api_key, model_name, base_url, llm_cfg['max_context_tokens'])
        token_manager = TokenManager(
            model_name=token_cfg['tokenizer_model_name'],
            reservation_tokens=token_cfg['prompt_template_reservation_tokens'],
            history_budget=token_cfg['history_truncation_budget']
        )
        semaphore = asyncio.Semaphore(config['concurrency_control']['reranker_concurrency_limit'])
        
        reranker = ParallelReranker(
            llm_service=llm_service,
            semaphore=semaphore,
            token_manager=token_manager,
            passage_id_key=config['vector_retriever']['passage_id_meta_key']
        )

        try:
            print("\n--- Step 1: Retrieving passages with VectorRetriever ---")
            # --- MODIFIED: Define both query types ---
            user_query = "আমার এনআইডি কার্ড হারিয়ে গেছে, এখন কি করব?"
            semantic_search_query = "হারিয়ে যাওয়া জাতীয় পরিচয়পত্র উত্তোলনের পদ্ধতি"
            filters = {"category": 'স্মার্ট কার্ড ও জাতীয়পরিচয়পত্র'}
            
            passages = await retriever.get_unique_passages_from_all_collections(semantic_search_query, filters=filters)
            
            if not passages:
                print("No passages retrieved. Cannot demonstrate reranker.")
                return

            print(f"\nRetrieved {len(passages)} passages, sorted by RRF score (top 5 shown):")
            for i, passage in enumerate(passages[:5]):
                passage_id = passage['metadata'].get(retriever.passage_id_key, 'N/A')
                print(f"  RRF Rank {i+1}: Passage ID: {passage_id}")

            print("\n--- Step 2: Reranking the retrieved passages with an LLM ---")
            reranked_results = await reranker.rerank(
                conversation_history=[],
                user_query=user_query,
                search_query=semantic_search_query, # <-- MODIFIED: Pass search_query
                passages=passages,
                **config['llm_call_parameters']['reranker']
            )

            print("\n--- Reranking Complete. Results: ---")
            for i, result in enumerate(reranked_results):
                print(f"\nOriginal RRF Rank: {i+1}")
                print(f"  Passage ID: {result.passage_id}")
                print(f"  LLM Score: {result.score}")
                print(f"  Reasoning: {result.reasoning}")

        except Exception as e:
            logging.error(f"An error occurred during the main execution: {e}", exc_info=True)
        finally:
            if 'retriever' in locals():
                retriever.close()
            print("\n--- Demo Finished ---")

    asyncio.run(main())