# FILE: cogops/utils/token_manager.py

from transformers import AutoTokenizer
from typing import List, Tuple, Dict, Any, Union
import logging

class TokenManager:
    """
    A utility class for managing token counts and truncating prompts to fit
    within a model's context window.
    """
    def __init__(self, model_name: str, reservation_tokens: int, history_budget: float):
        """
        Initializes the tokenizer and configuration for prompt building.

        Args:
            model_name (str): The Hugging Face model name for the tokenizer.
            reservation_tokens (int): A fixed number of tokens to reserve for prompt instructions.
            history_budget (float): The percentage of available tokens to allocate to history.
        """
        print(f"Initializing TokenManager with tokenizer from '{model_name}'...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.reservation_tokens = reservation_tokens
        self.history_budget = history_budget
        print(f"✅ TokenManager initialized. Reservation: {reservation_tokens} tokens, History Budget: {history_budget*100}%.")

    def count_tokens(self, text: str) -> int:
        """Counts the number of tokens in a given string."""
        if not text:
            return 0
        return len(self.tokenizer.encode(text))

    def _truncate_history(self, history: List[Tuple[str, str]], max_tokens: int) -> str:
        """
        Truncates conversation history from oldest to newest to fit the token budget.
        Returns a formatted string of the truncated history.
        """
        if not history:
            return "No conversation history yet."
            
        truncated_history = list(history)
        while truncated_history:
            formatted_history = "\n---\n".join([f"User: {u}\nAI: {a}" for u, a in truncated_history])
            if self.count_tokens(formatted_history) <= max_tokens:
                return formatted_history
            # Remove the oldest turn (from the beginning of the list)
            truncated_history.pop(0)
        
        # If even a single turn is too long, return an empty history string
        return "History is too long to be included."

    def _truncate_passages(self, passages: List[Dict[str, Any]], max_tokens: int) -> str:
        """
        Truncates a list of passages from last to first to fit the token budget.
        Returns a formatted string of the truncated passages.
        """
        if not passages:
            return ""

        # The input passages are assumed to be pre-sorted by relevance.
        # We truncate from the end of the list, removing the least relevant passages first.
        for i in range(len(passages), 0, -1):
            current_passages = passages[:i]
            context = "\n\n".join([f"Passage ID: {p.get('metadata', {}).get('passage_id', p.get('id'))}\nContent: {p['document']}" for p in current_passages])
            if self.count_tokens(context) <= max_tokens:
                return context
        
        # If even a single passage is too long, return an empty context
        return ""

    def build_safe_prompt(self, template: str, max_tokens: int, **kwargs: Dict[str, Any]) -> str:
        """
        Builds a prompt from a template and components, ensuring it does not
        exceed the maximum token limit through intelligent truncation.

        Args:
            template (str): The prompt template with placeholders like {history_str}.
            max_tokens (int): The maximum allowed tokens for the final prompt.
            **kwargs: The components to fill into the template (e.g., history, user_query).
        """
        # Calculate available tokens after reserving for boilerplate
        available_content_tokens = max_tokens - self.reservation_tokens

        # --- 1. Account for fixed, non-truncatable components ---
        tokens_used = 0
        final_components = {}
        for key, value in kwargs.items():
            # These are the keys for dynamic, truncatable content
            if key not in ['history', 'passages_context']:
                # All other kwargs are treated as fixed strings
                str_value = str(value)
                final_components[key] = str_value
                tokens_used += self.count_tokens(str_value)
        
        remaining_tokens = available_content_tokens - tokens_used
        if remaining_tokens < 0:
            # This can happen if the user query itself is extremely long
            logging.warning("Fixed components alone exceed token budget. Prompt will be truncated.")
            remaining_tokens = 0

        # --- 2. Allocate budget and truncate dynamic components ---
        history_str = ""
        passage_str = ""

        if 'history' in kwargs:
            history_budget_tokens = int(remaining_tokens * self.history_budget)
            history_str = self._truncate_history(kwargs['history'], history_budget_tokens)
            tokens_used += self.count_tokens(history_str)
        
        # Recalculate remaining tokens for passages
        passage_tokens_budget = available_content_tokens - tokens_used

        if 'passages_context' in kwargs:
            passage_str = self._truncate_passages(kwargs['passages_context'], passage_tokens_budget)
        
        # --- 3. Assemble the final prompt ---
        # Add the processed dynamic components to our final dictionary
        if 'history' in kwargs:
            final_components['history_str'] = history_str
        if 'passages_context' in kwargs:
            final_components['passages_context'] = passage_str

        # The template should expect keys like 'history_str' now
        final_prompt = template.format(**final_components)
        
        # Final safety check: hard truncate if something was miscalculated
        if self.count_tokens(final_prompt) > max_tokens:
            encoded_prompt = self.tokenizer.encode(final_prompt)
            truncated_encoded = encoded_prompt[:max_tokens]
            final_prompt = self.tokenizer.decode(truncated_encoded, skip_special_tokens=True)
            logging.warning("Prompt exceeded budget after assembly and was hard-truncated.")
            
        return final_prompt