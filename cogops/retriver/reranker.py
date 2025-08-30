# retriver/reranker.py

import os
import asyncio
from typing import List, Dict, Any, Literal, Optional
from pydantic import BaseModel
from cogops.models.gemma3_llm_async import AsyncLLMService

class RerankedPassage(BaseModel):
    """
    Represents a passage after it has been scored by the reranker.
    It now correctly stores the passage_id from the metadata.
    """
    passage_id: str  # The true passage identifier from the metadata
    score: Literal[1, 2, 3]
    reasoning: str
    document: str
    metadata: Optional[Dict[str, Any]] = None

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

    async def _score_one_passage(
        self,
        passage: Dict[str, Any],
        history: str,
        query: str,
        **llm_kwargs: Any
    ) -> RerankedPassage | None:
        """Helper coroutine to score a single passage and handle errors."""
        
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
                prompt, SinglePassageScore, **llm_kwargs
            )

            # --- MODIFIED SECTION ---
            # Extract the correct passage_id from the metadata.
            # Fallback to the document ID if metadata or passage_id is missing.
            passage_metadata = passage.get('metadata', {})
            correct_passage_id = passage_metadata.get('passage_id', passage['id'])
            # --- END MODIFIED SECTION ---

            return RerankedPassage(
                passage_id=str(correct_passage_id), # <-- Use the correct ID
                document=passage['document'],
                score=structured_response.score,
                reasoning=structured_response.reasoning,
                metadata=passage_metadata # <-- Pass the full metadata
            )
        except Exception as e:
            print(f"Could not score passage {passage['id']}. Error: {e}")
            return None

    async def rerank(
        self,
        conversation_history: str,
        user_query: str,
        passages: List[Dict[str, Any]],
        **llm_kwargs: Any
    ) -> List[RerankedPassage]:
        """
        Reranks a list of passages using parallel, structured LLM calls.
        """
        print(f"Reranking {len(passages)} passages in parallel...")
        
        tasks = [
            self._score_one_passage(p, conversation_history, user_query, **llm_kwargs)
            for p in passages
        ]
        
        results = await asyncio.gather(*tasks)
        successful_results = [res for res in results if res is not None]
        successful_results.sort(key=lambda x: x.score)
        
        return successful_results