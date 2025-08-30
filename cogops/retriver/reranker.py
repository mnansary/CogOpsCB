import os
import asyncio
from typing import List, Dict, Any, Literal
from pydantic import BaseModel
# --- Import the new AsyncLLMService ---
from cogops.models.gemma3_llm_async import AsyncLLMService 

class RerankedPassage(BaseModel):
    passage_id: str
    score: Literal[1, 2, 3]
    reasoning: str
    document: str # Keep the original document for easy access

RERANK_PROMPT_TEMPLATE = """
You are an expert relevance evaluation assistant. Your task is to determine if the provided PASSAGE is relevant for answering the USER QUERY, considering the CONVERSATION HISTORY.

Your evaluation must result in a score of 1, 2, or 3.
1: The passage directly and completely answers the user's query.
2: The passage is on-topic and partially relevant, but not a complete answer.
3: The passage is unrelated to the user's query.

CONVERSATION HISTORY:
{history}

USER QUERY:
{user_query}

PASSAGE:
{passage_text}
---
Based on all the information above, provide your relevance score and a brief justification.
"""

class ParallelReranker:
    def __init__(self, llm_service: AsyncLLMService):
        self.llm_service = llm_service
        print("✅ ParallelReranker initialized.")

    async def _score_one_passage(self, passage: Dict[str, Any], history: str, query: str) -> RerankedPassage | None:
        """Helper coroutine to score a single passage and handle errors."""
        
        # This is the Pydantic model for a single response
        class SinglePassageScore(BaseModel):
            score: Literal[1, 2, 3]
            reasoning: str
        
        prompt = RERANK_PROMPT_TEMPLATE.format(
            history=history or "No history provided.",
            user_query=query,
            passage_text=passage['document']
        )
        try:
            structured_response = await self.llm_service.invoke_structured(
                prompt, SinglePassageScore
            )
            return RerankedPassage(
                passage_id=passage['id'],
                document=passage['document'],
                score=structured_response.score,
                reasoning=structured_response.reasoning
            )
        except Exception as e:
            print(f"Could not score passage {passage['id']}. Error: {e}")
            return None # Return None on failure

    async def rerank(
        self,
        conversation_history: str,
        user_query: str,
        passages: List[Dict[str, Any]]
    ) -> List[RerankedPassage]:
        """
        Reranks a list of passages using parallel, structured LLM calls.
        """
        print(f"Reranking {len(passages)} passages in parallel...")
        
        # Create a list of tasks, one for each passage
        tasks = [
            self._score_one_passage(passage, conversation_history, user_query)
            for passage in passages
        ]
        
        # Run all tasks concurrently and wait for them to complete
        results = await asyncio.gather(*tasks)
        
        # Filter out any tasks that failed (returned None)
        successful_results = [res for res in results if res is not None]
        
        # Sort the successful results by score (1 is best)
        successful_results.sort(key=lambda x: x.score)
        
        return successful_results

# --- Example Usage ---
async def main():
    api_key = os.getenv("VLLM_SMALL_API_KEY") # Using the faster 4B/12B model is wise
    model = os.getenv("VLLM_SMALL_MODEL_NAME")
    base_url = os.getenv("VLLM_SMALL_BASE_URL")
    
    # 1. Initialize the ASYNC service
    llm = AsyncLLMService(api_key=api_key, model=model, base_url=base_url)
    
    # 2. Initialize the Reranker
    reranker = ParallelReranker(llm_service=llm)

    # 3. Dummy data
    retrieved_passages = [
        {'id': 'row_10', 'document': 'To reset your password, please visit the account settings page and click "Forgot Password".'},
        {'id': 'row_55', 'document': 'Our company was founded in 1998 and specializes in cloud solutions.'},
        {'id': 'row_23', 'document': 'You can change your password in the security section of your profile.'},
        {'id': 'row_99', 'document': 'The sky is blue due to Rayleigh scattering.'}
    ]

    # 4. Rerank the passages (this one 'await' runs all 4 calls concurrently)
    final_ranking = await reranker.rerank(
        conversation_history="User: I need help with my account.",
        user_query="How do I change my password?",
        passages=retrieved_passages
    )

    print("\n--- Final Parallel Reranked Results ---")
    for result in final_ranking:
        print(f"Passage ID: {result.passage_id}, Score: {result.score}, Reasoning: {result.reasoning}")

if __name__ == '__main__':
    asyncio.run(main())