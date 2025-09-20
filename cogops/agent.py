import os
import yaml
import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, List, Tuple

# Environment Variable Loading
from dotenv import load_dotenv
load_dotenv()

# --- Exception Imports for Network Errors ---
from openai import APIConnectionError, APITimeoutError
from requests.exceptions import RequestException

# --- Prompt Imports ---
from cogops.prompts.retrive import RetrievalPlan, retrive_prompt
from cogops.prompts.service import CATEGORY_LIST, SERVICE_DATA
from cogops.prompts.response import response_router
from cogops.prompts.answer import SYNTHESIS_ANSWER_PROMPT 
from cogops.prompts.summary import SUMMARY_GENERATION_PROMPT
from cogops.prompts.pivot import HELPFUL_PIVOT_PROMPT 

# --- Core Component Imports ---
from cogops.models.gemma3_llm import LLMService
from cogops.models.gemma3_llm_async import AsyncLLMService
from cogops.retriver.vector_search import VectorRetriever
from cogops.retriver.reranker import ParallelReranker
from cogops.utils.token_manager import TokenManager
from cogops.utils.string import refine_category

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class ChatAgent:
    """
    A configurable, end-to-end conversational agent for government services,
    orchestrating retrieval, reranking, and response generation with robust
    error handling for service unavailability.
    """
    def __init__(self, config_path: str = "configs/config.yaml"):
        logging.info("Initializing ChatAgent...")
        self.config = self._load_config(config_path)
        self.agent_name = self.config.get('agent_name', 'AI Assistant')
        self.agent_story = self.config.get('agent_story', 'I am a helpful AI assistant designed to provide information on government services.')

        # Initialize LLM Services
        self.llm_services_sync: Dict[str, LLMService] = {}
        self.llm_services_async: Dict[str, AsyncLLMService] = {}
        self._initialize_llm_services()

        # Map tasks to their configured async LLM service
        self.task_models_async = {
            task: self.llm_services_async[model_name]
            for task, model_name in self.config['task_to_model_mapping'].items()
        }

        # Initialize core components with parameters from config
        token_cfg = self.config['token_management']
        self.token_manager = TokenManager(
            model_name=token_cfg['tokenizer_model_name'],
            reservation_tokens=token_cfg['prompt_template_reservation_tokens'],
            history_budget=token_cfg['history_truncation_budget']
        )
        
        self.vector_retriever = VectorRetriever(config_path=config_path)
        
        reranker_concurrency = self.config['concurrency_control']['reranker_concurrency_limit']
        self.reranker_semaphore = asyncio.Semaphore(reranker_concurrency)
        
        self.reranker = ParallelReranker(
            llm_service=self.task_models_async['reranker'],
            semaphore=self.reranker_semaphore,
            token_manager=self.token_manager,
            passage_id_key=self.config['vector_retriever']['passage_id_meta_key']
        )

        # Load other configurations
        self.relevance_score_threshold = self.config['reranker']['relevance_score_threshold']
        self.history: List[Tuple[str, str]] = []
        self.raw_history: List[Tuple[str, str]] = []
        self.history_window = self.config['conversation']['history_window']
        self.llm_call_params = self.config['llm_call_parameters']
        self.response_templates = self.config['response_templates']
        self.category_refinement_cutoff = self.config['category_refinement']['score_cutoff']
        
        logging.info("✅ ChatAgent initialized successfully with the specified configuration.")

    def _load_config(self, config_path: str) -> Dict:
        logging.info(f"Loading configuration from: {config_path}")
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logging.error(f"[FATAL ERROR] Configuration file not found at: {config_path}")
            raise
    
    def _initialize_llm_services(self):
        logging.info("Initializing LLM services...")
        for name, cfg in self.config['llm_services'].items():
            api_key = os.getenv(cfg['api_key_env'])
            model = os.getenv(cfg['model_name_env'])
            url = os.getenv(cfg['base_url_env'])
            max_tokens = cfg.get('max_context_tokens', 8192)
            
            if not all([api_key, model, url]):
                raise ValueError(f"Missing environment variables for LLM service '{name}'")
                
            self.llm_services_sync[name] = LLMService(api_key, model, url, max_tokens)
            self.llm_services_async[name] = AsyncLLMService(api_key, model, url, max_tokens)
        logging.info("LLM services are ready.")

    def _format_history_for_planner(self) -> str:
        """
        MODIFIED: This now uses the raw, unabridged history to give the planner
        maximum context for understanding follow-up questions.
        """
        if not self.raw_history: return "No conversation history yet."
        return "\n---\n".join([f"User: {u}\nAI: {a}" for u, a in self.raw_history])

    async def process_query(self, user_query: str) -> AsyncGenerator[Dict[str, Any], None]:
        logging.info(f"\n--- New Query Received: '{user_query}' ---")
        
        try:
            # This call now uses the raw history via the updated method
            history_str_planner = self._format_history_for_planner()

            # --- 1. Generate Retrieval Plan ---
            planner_llm = self.task_models_async['retrieval_plan']
            planner_params = self.llm_call_params['retrieval_plan']
            planner_prompt = retrive_prompt.format(CATEGORY_LIST, history_str_planner, user_query)
            plan = await planner_llm.invoke_structured(planner_prompt, RetrievalPlan, **planner_params)
            logging.info(f"Retrieval Plan: {plan.model_dump_json(indent=2)}")

            # --- 2. Route Query Based on Plan ---
            if plan.query_type == "AMBIGUOUS" and plan.clarification:
                # For short interactions, raw and summarized histories are the same.
                self.history.append((user_query, plan.clarification))
                self.raw_history.append((user_query, plan.clarification))
                for char in plan.clarification:
                    yield {"type": "answer_chunk", "content": char}
                    await asyncio.sleep(0.01)
                return

            non_retrieval_types = ["OUT_OF_DOMAIN_GOVT_SERVICE_INQUIRY", 
                                   "GENERAL_KNOWLEDGE", 
                                   "CHITCHAT", 
                                   "ABUSIVE_SLANG",
                                   "IDENTITY_INQUIRY",
                                   "MALICIOUS",
                                   "UNHANDLED"]
            if plan.query_type in non_retrieval_types:
                responder_llm = self.task_models_async['non_retrieval_responder']
                responder_params = self.llm_call_params['non_retrieval_responder']
                prompt = response_router(plan.model_dump(), 
                                         history_str_planner, 
                                         user_query,
                                         agent_name=self.agent_name,
                                        agent_story=self.agent_story)
                full_answer_list=[]
                # Stream the response in chunks
                async for chunk in responder_llm.stream(prompt, **responder_params):
                    full_answer_list.append(chunk)
                    yield {"type": "answer_chunk", "content": chunk}
                # For short interactions, raw and summarized histories are the same.
                full_answer = "".join(full_answer_list)
                self.history.append((user_query, full_answer))
                self.raw_history.append((user_query, full_answer))

            elif plan.query_type == "IN_DOMAIN_GOVT_SERVICE_INQUIRY":
                # --- 3. Retrieval ---
                refined_cat = refine_category(plan.category, CATEGORY_LIST, self.category_refinement_cutoff)
                filters = {"category": refined_cat} if refined_cat else None
                retrieved = await self.vector_retriever.get_unique_passages_from_all_collections(plan.query, filters=filters)
                
                if not retrieved:
                    yield {"type": "answer_chunk", "content": self.response_templates['no_passages_found']}
                    return

                # --- 4. Reranking ---
                reranker_params = self.llm_call_params['reranker']
                reranked = await self.reranker.rerank(self.history, user_query, plan.query, retrieved, **reranker_params)
                
                relevant_passages = [p for p in reranked if p.score <= self.relevance_score_threshold]
                
                if not relevant_passages:
                    logging.warning("No highly relevant passages after reranking. Pivoting.")
                    responder_llm = self.task_models_async['non_retrieval_responder']
                    responder_params = self.llm_call_params['non_retrieval_responder']
                    pivot_prompt = HELPFUL_PIVOT_PROMPT.format(
                                    history_str=history_str_planner, 
                                    user_query=user_query, 
                                    category=refined_cat, 
                                    service_data=SERVICE_DATA
                                    )
                    full_answer_list = []
                    async for chunk in responder_llm.stream(pivot_prompt, **responder_params):
                        full_answer_list.append(chunk)
                        yield {"type": "answer_chunk", "content": chunk}
                    full_answer = "".join(full_answer_list)
                    self.raw_history.append((user_query, full_answer))
                    self.history.append((user_query, full_answer))
                    return

                # --- 5. Answer Generation ---
                answer_llm = self.task_models_async['answer_generator']
                answer_params = self.llm_call_params['answer_generator']
                answer_prompt = self.token_manager.build_safe_prompt(
                    template=SYNTHESIS_ANSWER_PROMPT,
                    max_tokens=answer_llm.max_context_tokens,
                    history=self.history,
                    user_query=user_query,
                    passages_context=relevant_passages
                )
                
                full_answer_list = []
                async for chunk in answer_llm.stream(answer_prompt, **answer_params):
                    full_answer_list.append(chunk)
                    yield {"type": "answer_chunk", "content": chunk}
                final_answer = "".join(full_answer_list).strip()

                # --- 6. Finalization (Sources & Summarization) ---
                unique_urls = {p.metadata.get("url") for p in relevant_passages if p.metadata and p.metadata.get("url")}
                unique_passage_ids = {p.passage_id for p in relevant_passages}
                final_sources = sorted(list(unique_urls)) + sorted(list(unique_passage_ids))
                yield {"type": "final_data", "content": {"sources": final_sources}}

                # MODIFIED: Populate the two history lists with different content
                self.raw_history.append((user_query, final_answer))

                summarizer_llm = self.task_models_async['summarizer']
                summarizer_params = self.llm_call_params['summarizer']
                summary_prompt = SUMMARY_GENERATION_PROMPT.format(user_query=user_query, final_answer=final_answer)
                summary = await summarizer_llm.invoke(summary_prompt, **summarizer_params)
                self.history.append((user_query, summary.strip()))

            # MODIFIED: Truncate both history lists to keep them in sync
            if len(self.history) > self.history_window:
                self.history.pop(0)
            if len(self.raw_history) > self.history_window:
                self.raw_history.pop(0)

        except (APIConnectionError, APITimeoutError, RequestException) as e:
            # --- CATCH BLOCK for Service Unavailability ---
            logging.error(f"A network service is unavailable. Underlying error: {e}")
            yield {"type": "error", "content": "Network error : services unavailable due to load"}
            return
        
        except Exception as e:
            # Catch any other unexpected errors during processing
            logging.error(f"An unexpected error occurred during query processing: {e}", exc_info=True)
            yield {"type": "error", "content": self.response_templates['error_fallback']}
            return


async def main():
    """Main function to demonstrate a conversational flow with the ChatAgent."""
    try:
        agent = ChatAgent(config_path="configs/config.yaml")
        
        queries = [
            "আমার এনআইডি কার্ড হারিয়ে গেছে, এখন কি করব?",
            "এর জন্য কি কোনো ফি দিতে হবে?",
            "ধন্যবাদ। এখন বলুন পাসপোর্ট নবায়ন করতে কি কি লাগে?",
            "বাংলাদেশের রাজধানীর নাম কি?"
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
                    # This block will now handle both regular errors and our new network error
                    print(f"\n[AGENT ERROR] {event['content']}")
            
            if final_data:
                print(f"\n\n--- Final Data Received ---\n{final_data}")
            print("\n")
            
    except Exception as e:
        logging.error(f"A fatal error occurred during agent initialization or execution: {e}", exc_info=True)
    finally:
        if 'agent' in locals() and hasattr(agent, 'vector_retriever'):
            agent.vector_retriever.close()


if __name__ == "__main__":
    asyncio.run(main())