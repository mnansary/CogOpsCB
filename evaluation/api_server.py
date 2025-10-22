import os
import json
import logging
import csv
import threading
from datetime import datetime
from itertools import chain, combinations
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field

# --- Core Application Logic Imports ---
from evaluation.retriver import DynamicVectorRetriever
from evaluation.query_formatter import QueryFormatter
from cogops.models.qwen3async_llm import AsyncLLMService
from fastapi.middleware.cors import CORSMiddleware

# --- Setup Logging & App ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = FastAPI(
    title="Q&A Retrieval Evaluation API",
    description="An API to test and evaluate different retrieval models and query formatting strategies."
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration ---
DATA_DIR = Path("/home/vpa/Documents/qna_data")
EVAL_CSV_PATH = Path("/home/vpa/Documents/eval_results.csv")
CSV_HEADER = [
    "date_time", "model_name", "passage_id", "query_index",
    "p1_val", "p1_score", "p2_val", "p2_score", "p3_val", "p3_score"
]
# A thread lock to prevent race conditions when writing to the CSV file
csv_lock = threading.Lock()

# --- Global Singletons ---
retriever: DynamicVectorRetriever = None
formatter: QueryFormatter = None

# --- Pydantic Models for API Data Validation ---
class PassageDetailsResponse(BaseModel):
    passage: str
    question_indexes: List[int]

class QuestionResponse(BaseModel):
    question: str

class RetrievalRequest(BaseModel):
    passage_id: str = Field(..., description="The ID of the passage containing the question.")
    question_index: int = Field(..., gt=0, description="The 1-based index of the question to use as the query.")
    model_name: str = Field(..., description="The name of the retrieval model to use (e.g., 'qwen3_ques_prop').")

class EvaluationResultRequest(BaseModel):
    model_name: str
    passage_id: str
    query_index: int
    p1_val: str
    p2_val: str
    p3_val: str
    p1_score: int
    p2_score: int
    p3_score: int

# --- Helper Functions ---
def get_passage_data(passage_id: str) -> Dict[str, Any]:
    """Loads and returns the content of a passage JSON file."""
    file_path = DATA_DIR / f"{passage_id}.json"
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Passage ID '{passage_id}' not found.")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error reading or parsing {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not process data for passage ID '{passage_id}'.")

# --- Startup Event to Initialize Heavy Models ---
@app.on_event("startup")
async def startup_event():
    """Initializes the retriever and query formatter when the API starts."""
    global retriever, formatter
    logging.info("API starting up...")
    
    if not DATA_DIR.is_dir():
        logging.error(f"CRITICAL: Data directory not found at {DATA_DIR}. Endpoints will fail.")
    else:
        logging.info(f"Data directory found at {DATA_DIR}")

    try:
        retriever = DynamicVectorRetriever()
        llm_client = AsyncLLMService(
            api_key=os.getenv("VLLM_API_KEY"),
            model=os.getenv("VLLM_MODEL_NAME"),
            base_url=os.getenv("VLLM_BASE_URL"),
            max_context_tokens=32000
        )
        formatter = QueryFormatter(llm_service=llm_client)
        logging.info("✅ Successfully initialized DynamicVectorRetriever and QueryFormatter.")
    except Exception as e:
        logging.error(f"CRITICAL: Failed to initialize models on startup: {e}")

# --- API Endpoints ---
@app.get("/get_passage_list", response_model=List[str], tags=["Data Access"])
def get_passage_list():
    """Returns a list of all available passage IDs from the data directory."""
    if not DATA_DIR.is_dir():
        raise HTTPException(status_code=500, detail="Server data directory is not configured.")
    
    passage_ids = sorted([p.stem for p in DATA_DIR.glob("*.json")])
    return passage_ids

@app.get("/get_question_list", response_model=PassageDetailsResponse, tags=["Data Access"])
def get_question_list(passage_id: str):
    """
    Given a passage_id, returns the passage text and a 1-indexed list of its question indexes.
    """
    data = get_passage_data(passage_id)
    num_questions = data.get("num_questions", 0)
    
    return {
        "passage": data.get("passage", ""),
        "question_indexes": list(range(1, num_questions + 1))
    }

@app.get("/get_question", response_model=QuestionResponse, tags=["Data Access"])
def get_question(passage_id: str, question_index: int):
    """
    Given a passage_id and a 1-based question_index, returns the specific question text.
    """
    if question_index <= 0:
        raise HTTPException(status_code=400, detail="question_index must be a positive integer (1-based).")
        
    data = get_passage_data(passage_id)
    questions = data.get("questions", [])
    zero_based_index = question_index - 1
    
    if not (0 <= zero_based_index < len(questions)):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid question_index. Passage '{passage_id}' has only {len(questions)} questions."
        )
        
    return {"question": questions[zero_based_index]}

@app.get("/get_models", response_model=List[str], tags=["Retrieval & Evaluation"])
def get_models():
    """
    Generates and returns a list of all possible model names for retrieval.
    """
    parts = ["prop", "summ", "ques"]
    all_combinations = []
    
    for i in range(1, len(parts) + 1):
        for combo in combinations(parts, i):
            all_combinations.append("_".join(combo))

    embgemma_models = [f"embGemma_{c}" for c in all_combinations]
    qwen3_models = [f"qwen3_{c}" for c in all_combinations]
    
    return sorted(embgemma_models + qwen3_models)

@app.post("/get_model_based_passage_data", tags=["Retrieval & Evaluation"])
async def get_model_based_passage_data(request: RetrievalRequest):
    """
    The core retrieval endpoint. It fetches a query, conditionally formats it, and retrieves relevant passages.
    """
    if retriever is None or formatter is None:
        raise HTTPException(status_code=503, detail="Models are not initialized. Please check server logs.")

    question_response = get_question(request.passage_id, request.question_index)
    user_query = question_response["question"]
    logging.info(f"Retrieved user query: '{user_query}'")
    
    query_dict = {}
    
    if request.model_name.startswith("qwen3_"):
        logging.info(f"'{request.model_name}' requires query formatting. Using QueryFormatter.")
        try:
            query_dict = await formatter.format(user_query, request.model_name)
        except Exception as e:
            logging.error(f"QueryFormatter failed for model '{request.model_name}': {e}")
            raise HTTPException(status_code=500, detail=f"Query formatting failed: {e}")
            
    elif request.model_name.startswith("embGemma_"):
        logging.info(f"'{request.model_name}' uses direct retrieval. Creating simple query_dict.")
        required_parts = request.model_name.split('_')[1:]
        key_map = {'prop': 'proposition', 'summ': 'summary', 'ques': 'question'}
        for part in required_parts:
            key = key_map.get(part)
            if key:
                query_dict[key] = user_query
    else:
        raise HTTPException(status_code=400, detail="Invalid model_name prefix. Must start with 'qwen3_' or 'embGemma_'.")

    logging.info(f"Executing retrieval with query_dict: {query_dict}")
    
    try:
        retrieved_passages = await retriever.retrieve_passages(query_dict, request.model_name)
        return retrieved_passages
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"Retrieval process failed: {e}")
        raise HTTPException(status_code=500, detail="An error occurred during passage retrieval.")

@app.post("/save_evaluation_result", tags=["Retrieval & Evaluation"])
def save_evaluation_result(result: EvaluationResultRequest):
    """
    Saves a human evaluation result to a persistent CSV file.
    This endpoint is thread-safe.
    """
    # Ensure the parent directory exists
    try:
        EVAL_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logging.error(f"Could not create directory for CSV file: {e}")
        raise HTTPException(status_code=500, detail="Server misconfiguration: cannot create results directory.")

    # Using a lock to prevent race conditions when writing to the file
    with csv_lock:
        try:
            # Check if the file exists to determine if we need to write a header
            file_exists = EVAL_CSV_PATH.is_file()

            # 'a' mode for append, newline='' is crucial for csv writer
            with open(EVAL_CSV_PATH, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Write the header only if the file is new
                if not file_exists:
                    writer.writerow(CSV_HEADER)
                
                # Prepare the data row in the correct order
                data_row = [
                    datetime.now().isoformat(),
                    result.model_name,
                    result.passage_id,
                    result.query_index,
                    result.p1_val,
                    result.p1_score,
                    result.p2_val,
                    result.p2_score,
                    result.p3_val,
                    result.p3_score
                ]
                writer.writerow(data_row)

        except Exception as e:
            logging.error(f"Failed to write to CSV file {EVAL_CSV_PATH}: {e}")
            raise HTTPException(status_code=500, detail="Failed to save evaluation result.")

    return {"status": "success", "message": "Evaluation result saved."}