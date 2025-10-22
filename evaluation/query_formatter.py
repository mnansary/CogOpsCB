import os
import json
import asyncio
import logging
from typing import Dict, Type
from dotenv import load_dotenv
from pydantic import BaseModel, Field, create_model
from cogops.models.qwen3async_llm import AsyncLLMService


# --- Setup Logging & Environment ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Define the schemas for each component using Pydantic Fields ---
# These descriptions are crucial instructions for the LLM.
COMPONENT_SCHEMAS = {
    "prop": ("proposition", Field(
        ...,  # The '...' indicates a required field and must come first.
        description="A hypothetical, declarative statement of fact that a perfect answer document would contain. This should be a full sentence, not a question or title."
    )),
    "summ": ("summary", Field(
        ...,
        description="A concise, title-like summary of the user's core need. Should be a short phrase optimized for semantic search."
    )),
    "ques": ("question", Field(
        ...,
        description="A well-formed, context-free question that a perfect answer document would respond to. It must be a complete, standalone question."
    ))
}

# --- The Master Prompt for Query Transformation ---
QUERY_TRANSFORMATION_PROMPT = """
You are an expert Query Analyst for a search system that indexes passages of text from Bangladesh government documents.
Your sole task is to transform a raw user query into a structured JSON object containing one or more specialized search queries (`proposition`, `summary`, `question`).
You MUST NOT answer the user's query. Your only output is the generated JSON.

**Conceptual Framework: How Passages are Indexed**
To understand your task, first understand how our data is structured. We start with a passage of text and decompose it. Your goal is to reverse-engineer the decomposed parts from a user's query.

*Source Passage Example:*
```json
{{
    "text": "স্মার্ট কার্ড পেতে প্রথমে www.nidw.gov.bd ওয়েবসাইটে গিয়ে স্ট্যাটাস চেক করুন। তারপর নিজের উপজেলা নির্বাচন অফিসে যান এবং পুরোনো এনআইডি/স্লিপ জমা দিয়ে স্মার্ট কার্ড সংগ্রহ করতে পারবেন। যদি ওয়েবসাইটে 'তথ্য পাওয়া যায়নি' লেখা দেখায়, তাহলে আপনার কার্ড এখনও প্রিন্ট হয়নি।",
    "propositions": [
        "স্মার্ট কার্ড পেতে www.nidw.gov.bd ওয়েবসাইটে গিয়ে স্ট্যাটাস চেক করতে হয়।",
        "উপজেলা নির্বাচন অফিসে পুরোনো এনআইডি/স্লিপ জমা দিয়ে স্মার্ট কার্ড সংগ্রহ করা যায়।"
    ],
    "summaries": [
        "স্মার্ট কার্ড পাওয়ার প্রক্রিয়া",
        "স্মার্ট কার্ডের স্ট্যাটাস যাচাই"
    ],
    "questions": [
        "স্মার্ট কার্ড কিভাবে পাওয়া যাবে?",
        "স্মার্ট কার্ডের স্ট্যাটাস কিভাবে চেক করতে হয়?",
        "স্মার্ট কার্ড কোথা থেকে সংগ্রহ করতে হয়?"
    ]
}}
```

**Your Task & Instructions:**
Based on the user's query below, generate the required search components as a JSON object.
1.  Analyze the user's query to understand their true goal.
2.  Generate only the fields specified in the target JSON Schema (`proposition`, `summary`, `question`).
3.  Each generated field must be a high-quality, relevant transformation, optimized for finding passages like the one above.
4.  Your output MUST be a single, valid JSON object that strictly adheres to the schema.

---
**User Query:** `{user_query}`
---

**Gold-Standard Examples:**

*   **Example 1:**
    *   User Query: `রাজশাহীতে স্মার্ট কার্ড কই দেয় ?`
    *   Target Schema: `{{"question": "string"}}`
    *   Correct JSON Output: `{{"question": "স্মার্ট কার্ড কোথা থেকে সংগ্রহ করতে হয়?"}}`

*   **Example 2:**
    *   User Query: `আমার বাবা মুক্তি যোদ্ধা কিন্তু সনদ নাই কি করবো ?`
    *   Target Schema: `{{"summary": "string"}}`
    *   Correct JSON Output: `{{"summary": "মুক্তিযোদ্ধা সনদপত্র পাওয়ার উপায়"}}`

*   **Example 3:**
    *   User Query: `How do I apply for a lost NID card?`
    *   Target Schema: `{{"proposition": "string", "question": "string"}}`
    *   Correct JSON Output: `{{"proposition": "The procedure for a lost NID card requires filing a police report and then applying online.", "question": "What is the process to get a replacement NID card?"}}`

*   **Example 4:**
    *   User Query: `আমার জন্ম নিবন্ধন সনদে বাবার নাম ভুল আছে, কিভাবে ঠিক করবো?`
    *   Target Schema: `{{"proposition": "string", "summary": "string", "question": "string"}}`
    *   Correct JSON Output: `{{"proposition": "Birth registration certificates with incorrect father's names can be corrected by applying at the respective registrar's office with supporting documents.", "summary": "জন্ম নিবন্ধন সনদ সংশোধন প্রক্রিয়া", "question": "জন্ম নিবন্ধন সনদে ভুল তথ্য কিভাবে সংশোধন করা যায়?"}}`

**JSON Schema for your output:**
```json
{schema_json}
```
"""


class QueryFormatter:
    """
    A class to transform natural language queries into structured JSON objects
    for dynamic, multi-pipeline retrieval systems.
    """
    def __init__(self, llm_service: AsyncLLMService):
        """
        Initializes the formatter with a pre-configured LLM client.
        Args:
            llm_service: An instance of a class like AsyncLLMService.
        """
        if not hasattr(llm_service, 'invoke_structured'):
            raise TypeError("llm_service must have an 'invoke_structured' async method.")
        self.llm_service = llm_service

    def _create_dynamic_model(self, model_name: str) -> Type[BaseModel]:
        """
        Creates a Pydantic model on-the-fly based on the model_name string.
        """
        active_pipelines = model_name.split('_')[1:]
        fields_to_create = {}
        
        for pipe in active_pipelines:
            if pipe not in COMPONENT_SCHEMAS:
                raise ValueError(f"Invalid pipeline part '{pipe}' in model name '{model_name}'. Valid parts are: {list(COMPONENT_SCHEMAS.keys())}")
            
            field_name, field_definition = COMPONENT_SCHEMAS[pipe]
            fields_to_create[field_name] = (str, field_definition)  # (type, Field)

        if not fields_to_create:
            raise ValueError(f"Could not determine any valid pipelines from model_name: {model_name}")
        
        return create_model('DynamicQueryModel', **fields_to_create)

    async def format(self, user_query: str, model_name: str) -> Dict:
        """
        Generates the structured retrieval JSON for a given user query and model schema.

        Args:
            user_query: The natural language query from the user.
            model_name: The model schema identifier (e.g., 'embGemma_ques_prop').

        Returns:
            A dictionary matching the schema defined by the model_name.
        """
        logging.info(f"Formatting query '{user_query[:50]}...' for model '{model_name}'")
        
        # 1. Dynamically build the Pydantic model and its schema
        DynamicQueryModel = self._create_dynamic_model(model_name)
        schema_json = json.dumps(DynamicQueryModel.model_json_schema(), indent=2)
        
        # 2. Prepare the prompt
        prompt = QUERY_TRANSFORMATION_PROMPT.format(
            user_query=user_query,
            schema_json=schema_json
        )
        
        # 3. Call the LLM for a structured response
        try:
            structured_response = await self.llm_service.invoke_structured(
                prompt,
                DynamicQueryModel,
                temperature=0.0  # Low temp for deterministic and high-quality JSON
            )
            return structured_response.model_dump()
        except Exception as e:
            logging.error(f"LLM failed to generate valid JSON for query '{user_query}': {e}")
            raise

# --- Main execution block for testing ---
async def main():
    """Demonstrates and tests the QueryFormatter."""
    
    # --- LLM Client Initialization ---
    # This part should be handled by your application's main logic.
    # We do it here to make the script runnable for testing.
    try:
        API_KEY = os.getenv("VLLM_API_KEY")
        MODEL_NAME = os.getenv("VLLM_MODEL_NAME")
        BASE_URL = os.getenv("VLLM_BASE_URL")
        llm_client = AsyncLLMService(API_KEY, MODEL_NAME, BASE_URL, max_context_tokens=32000)
    except (ValueError, NotImplementedError) as e:
        print(f"Could not initialize real LLM service: {e}. Exiting test.")
        return

    formatter = QueryFormatter(llm_service=llm_client)

    test_cases = [
        {"model_name": "embGemma_ques", "query": "স্মার্ট কার্ডের স্ট্যাটাস কিভাবে চেক করবো?"},
        {"model_name": "embGemma_summ", "query": "e-passport renewal"},
        {"model_name": "embGemma_prop", "query": "ভূমি উন্নয়ন কর পরিশোধের শেষ তারিখ কবে?"},
        {"model_name": "embGemma_ques_prop", "query": "If I lose my NID, what should I do?"},
        {"model_name": "embGemma_prop_summ_ques", "query": "আমার ট্রেড লাইসেন্সের মেয়াদ শেষ, নবায়ন করতে চাই, খরচ কত হবে আর কি কি লাগবে?"},
    ]
    
    for test in test_cases:
        print("\n" + "="*50)
        print(f"Testing Model: {test['model_name']}")
        print(f"User Query: {test['query']}")
        print("="*50)
        
        try:
            result_json = await formatter.format(
                user_query=test['query'],
                model_name=test['model_name']
            )
            print("✅ Generated JSON:")
            print(json.dumps(result_json, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"❌ Test Failed: {e}")

if __name__ == "__main__":
    # To run this script directly, ensure your .env file has the VLLM variables
    # and the cogops.models.qwen3async_llm module is accessible.
    asyncio.run(main())