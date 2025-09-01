import os
import yaml
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Tuple

# Environment Variable Loading
from dotenv import load_dotenv
load_dotenv()

# --- Prompt Imports ---
from cogops.prompts.retrive import RetrievalPlan, retrive_prompt
from cogops.prompts.service import CATEGORY_LIST,SERVICE_DATA
from cogops.prompts.response import response_router
from cogops.prompts.answer import ANSWER_GENERATION_PROMPT,SYNTHESIS_ANSWER_PROMPT 
from cogops.prompts.summary import SUMMARY_GENERATION_PROMPT
from cogops.prompts.pivot import HELPFUL_PIVOT_PROMPT 

# --- Core Component Imports ---
from cogops.models.gemma3_llm import LLMService
from cogops.models.gemma3_llm_async import AsyncLLMService
from cogops.retriver.vector_search import VectorRetriever
from cogops.retriver.reranker import ParallelReranker
from cogops.utils.string import refine_category


class ChatAgent:
    """
    A configurable, end-to-end conversational agent for government services,
    orchestrating retrieval, reranking, and response generation.
    """
    def __init__(self, config_path: str = "configs/config.yaml"):
        print("Initializing ChatAgent...")
        self.config = self._load_config(config_path)
        self.llm_services_sync: Dict[str, LLMService] = {}
        self.llm_services_async: Dict[str, AsyncLLMService] = {}
        self._initialize_llm_services()
        self.task_models_async = {
            task: self.llm_services_async[model_name]
            for task, model_name in self.config['task_to_model_mapping'].items()
        }
        self.vector_retriever = VectorRetriever(config_path=config_path)
        self.reranker = ParallelReranker(llm_service=self.task_models_async['reranker'])
        self.relevance_score_threshold = self.config['reranker']['relevance_score_threshold']
        self.history: List[Tuple[str, str]] = []
        self.history_window = self.config['conversation']['history_window']
        self.llm_call_params = self.config['llm_call_parameters']
        self.response_templates = self.config['response_templates']
        self.category_refinement_cutoff = self.config['category_refinement']['score_cutoff']
        print("✅ ChatAgent initialized successfully with the specified configuration.")

    def _load_config(self, config_path: str) -> Dict:
        print(f"Loading configuration from: {config_path}")
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"[FATAL ERROR] Configuration file not found at: {config_path}")
            raise
    
    def _initialize_llm_services(self):
        print("Initializing LLM services...")
        for name, cfg in self.config['llm_services'].items():
            api_key, model, url = os.getenv(cfg['api_key_env']), os.getenv(cfg['model_name_env']), os.getenv(cfg['base_url_env'])
            if not all([api_key, model, url]):
                raise ValueError(f"Missing environment variables for LLM service '{name}'")
            self.llm_services_sync[name] = LLMService(api_key, model, url)
            self.llm_services_async[name] = AsyncLLMService(api_key, model, url)
        print("LLM services are ready.")

    def _format_history(self) -> str:
        if not self.history: return "No conversation history yet."
        return "\n---\n".join([f"User: {u}\nAI: {a}" for u, a in self.history])

    async def process_query(self, user_query: str) -> AsyncGenerator[Dict[str, Any], None]:
        print(f"\n--- New Query Received: '{user_query}' ---")
        history_str = self._format_history()

        try:
            planner_llm = self.task_models_async['retrieval_plan']
            planner_params = self.llm_call_params['retrieval_plan']
            planner_prompt = retrive_prompt.format(CATEGORY_LIST, history_str, user_query)
            plan = await planner_llm.invoke_structured(planner_prompt, RetrievalPlan, **planner_params)
            print(f"Retrieval Plan: {plan.model_dump_json(indent=2)}")
        except Exception as e:
            print(f"[ERROR] Failed to generate a valid retrieval plan: {e}")
            yield {"type": "error", "content": self.response_templates['plan_generation_failed']}
            return

        if plan.query_type == "AMBIGUOUS" and plan.clarification:
            self.history.append((user_query, plan.clarification))
            for char in plan.clarification:
                yield {"type": "answer_chunk", "content": char}
                await asyncio.sleep(0.01)
            return

        non_retrieval_types = ["OUT_OF_DOMAIN_GOVT_SERVICE_INQUIRY", "GENERAL_KNOWLEDGE", "CHITCHAT", "ABUSIVE_SLANG"]
        if plan.query_type in non_retrieval_types:
            responder_llm = self.task_models_async['non_retrieval_responder']
            responder_params = self.llm_call_params['non_retrieval_responder']
            prompt = response_router(plan.model_dump(), history_str, user_query)
            full_answer = "".join([chunk async for chunk in responder_llm.stream(prompt, **responder_params)])
            yield {"type": "answer_chunk", "content": full_answer}
            self.history.append((user_query, full_answer))

        elif plan.query_type == "IN_DOMAIN_GOVT_SERVICE_INQUIRY":
            refined_cat = refine_category(plan.category, CATEGORY_LIST, self.category_refinement_cutoff)
            filters = {"category": refined_cat} if refined_cat else None
            retrieved = await self.vector_retriever.get_unique_passages_from_all_collections(plan.query, filters=filters)
            if not retrieved:
                yield {"type": "answer_chunk", "content": self.response_templates['no_passages_found']}
                return

            reranker_params = self.llm_call_params['reranker']
            reranked = await self.reranker.rerank(history_str, user_query, retrieved, **reranker_params)
            relevant_passages = [p for p in reranked if p.score <= self.relevance_score_threshold]
            # --- MODIFIED SECTION: What to do when no relevant passages are found ---
            if not relevant_passages:
                print("No highly relevant passages found. Generating a helpful pivot response.")
                
                # Use the responder model and its params for this generative task
                responder_llm = self.task_models_async['non_retrieval_responder']
                responder_params = self.llm_call_params['non_retrieval_responder']
                
                # Format the new pivot prompt
                pivot_prompt = HELPFUL_PIVOT_PROMPT.format(
                    history=history_str,
                    user_query=user_query,
                    category=refined_cat,
                    service_data=SERVICE_DATA
                )

                # Stream the dynamically generated pivot response
                full_answer_list = []
                async for chunk in responder_llm.stream(pivot_prompt, **responder_params):
                    full_answer_list.append(chunk)
                    yield {"type": "answer_chunk", "content": chunk}
                
                final_answer = "".join(full_answer_list).strip()
                # IMPORTANT: Add this interaction to history
                self.history.append((user_query, final_answer))
                return # End the processing here for this query
            # --- END MODIFIED SECTION ---

            context = "\n\n".join([f"Passage ID: {p.passage_id}\nContent: {p.document}" for p in relevant_passages])
            answer_llm = self.task_models_async['answer_generator']
            answer_params = self.llm_call_params['answer_generator']
            answer_prompt = SYNTHESIS_ANSWER_PROMPT.format(history=history_str, user_query=user_query, passages_context=context)
            
            full_answer_list = []
            async for chunk in answer_llm.stream(answer_prompt, **answer_params):
                full_answer_list.append(chunk)
                yield {"type": "answer_chunk", "content": chunk}
            final_answer = "".join(full_answer_list).strip()

            # --- MODIFIED SECTION: Building the Final Sources List ---
            unique_urls = set()
            unique_passage_ids = set()
            
            for passage in relevant_passages:
                # Add the correct passage_id from the reranked object
                unique_passage_ids.add(passage.passage_id)
                
                # If metadata and a URL exist, add the URL
                if passage.metadata and passage.metadata.get("url"):
                    unique_urls.add(passage.metadata["url"])

            # Combine sorted lists for a deterministic output
            final_sources = sorted(list(unique_urls)) + sorted(list(unique_passage_ids))
            # --- END MODIFIED SECTION ---

            yield {"type": "final_data", "content": {"sources": final_sources}}

            summarizer_llm = self.task_models_async['summarizer']
            summarizer_params = self.llm_call_params['summarizer']
            summary_prompt = SUMMARY_GENERATION_PROMPT.format(user_query=user_query, final_answer=final_answer)
            summary = await summarizer_llm.invoke(summary_prompt, **summarizer_params)
            self.history.append((user_query, summary.strip()))
            #self.history.append((user_query, final_answer.strip()))

        if len(self.history) > self.history_window:
            self.history.pop(0)


async def main():
    """Main function to demonstrate the fully configured ChatAgent."""
    try:
        agent = ChatAgent(config_path="configs/config.yaml")
        queries = [
            "হ্যালো, কেমন আছো?",
            "আমার এনআইডি কার্ড হারিয়ে গেছে, এখন কি করব?",
            "সেটার জন্য কত টাকা লাগবে?",
            "আমি মাছ ধরার লাইসেন্স করতে চাই।",
            "what is the capital of france"
        ]

        for query in queries:
            print("\n" + "="*50 + f"\nUser Query: {query}\n" + "="*50)
            print("AI Response: ", end="", flush=True)
            final_data = None
            
            async for event in agent.process_query(query):
                if event["type"] == "answer_chunk":
                    print(event["content"], end="", flush=True)
                elif event["type"] == "final_data":
                    final_data = event["content"]
                elif event["type"] == "error":
                    print(f"\n[ERROR] {event['content']}")
            
            if final_data:
                print(f"\n\n--- Final Data Received ---\n{final_data}")
            print("\n")
            
    except Exception as e:
        print(f"\nAn error occurred during the main execution: {e}")


if __name__ == "__main__":
    asyncio.run(main())