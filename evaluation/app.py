import streamlit as st
import requests
import pandas as pd
from typing import List, Dict, Any

# --- CONFIGURATION ---
API_BASE_URL = "http://127.0.0.1:9051"
SCORING_MAP = {
    'Exact Match': 1,
    'Relevant': 2,
    'Irrelevant': 3
}
SCORING_OPTIONS = list(SCORING_MAP.keys())

# --- API HELPER FUNCTIONS ---
# These functions handle communication with your FastAPI backend.

def get_api_data(endpoint: str, params: Dict = None) -> Any:
    """Generic function to handle GET requests to the API."""
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", params=params)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.ConnectionError:
        st.error(f"Connection Error: Could not connect to the API at {API_BASE_URL}. Is the server running?")
        return None
    except requests.exceptions.HTTPError as e:
        st.error(f"API Error: Failed to fetch data from {endpoint}. Status Code: {e.response.status_code}. Message: {e.response.text}")
        return None

def post_api_data(endpoint: str, payload: Dict) -> Any:
    """Generic function to handle POST requests to the API."""
    try:
        response = requests.post(f"{API_BASE_URL}{endpoint}", json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        st.error(f"Connection Error: Could not connect to the API at {API_BASE_URL}. Is the server running?")
        return None
    except requests.exceptions.HTTPError as e:
        st.error(f"API Error: Failed to post data to {endpoint}. Status Code: {e.response.status_code}. Message: {e.response.text}")
        return None

# --- SESSION STATE INITIALIZATION ---
# This ensures that data persists between user interactions.
def initialize_state():
    """Initializes keys in the session state if they don't exist."""
    if 'passage_list' not in st.session_state:
        st.session_state.passage_list = []
    if 'model_list' not in st.session_state:
        st.session_state.model_list = []
    if 'retrieved_passages' not in st.session_state:
        st.session_state.retrieved_passages = []
    if 'scores' not in st.session_state:
        st.session_state.scores = {}
    if 'current_query_text' not in st.session_state:
        st.session_state.current_query_text = ""

# --- MAIN APP LAYOUT ---
def main():
    st.set_page_config(layout="wide", page_title="Retrieval Evaluator")
    initialize_state()

    st.title("Retrieval Model Evaluation Interface")
    st.markdown("Select a passage and a query, choose a retrieval model, and score the results.")

    # --- Load initial data from API on first run ---
    if not st.session_state.passage_list:
        st.session_state.passage_list = get_api_data("/get_passage_list") or []
    if not st.session_state.model_list:
        st.session_state.model_list = get_api_data("/get_models") or []
    
    # --- UI: SELECTION COLUMNS ---
    col1, col2 = st.columns(2)

    with col1:
        st.header("1. Select Source Data")
        selected_passage_id = st.selectbox(
            "Select a Passage ID",
            options=st.session_state.passage_list,
            index=None, # No default selection
            placeholder="Choose a passage..."
        )

    with col2:
        st.header("2. Select Retrieval Model")
        selected_model = st.selectbox(
            "Select a Model",
            options=st.session_state.model_list,
            index=None,
            placeholder="Choose a model..."
        )

    st.divider()

    # --- UI: DISPLAY SOURCE DATA & RUN EVALUATION ---
    if selected_passage_id:
        # Fetch details for the selected passage
        passage_details = get_api_data("/get_question_list", params={"passage_id": selected_passage_id})
        
        if passage_details:
            with st.expander("View Source Passage Text", expanded=False):
                st.text_area("Passage Text", passage_details['passage'], height=200, disabled=True)

            selected_question_index = st.selectbox(
                "Select a Question Index to use as Query",
                options=passage_details['question_indexes'],
                index=None,
                placeholder="Choose a question..."
            )

            if selected_question_index:
                # Get the actual question text
                query_data = get_api_data("/get_question", params={"passage_id": selected_passage_id, "question_index": selected_question_index})
                if query_data:
                    st.session_state.current_query_text = query_data['question']
                    st.info(f"**Selected Query:** {st.session_state.current_query_text}")

    # --- Run Button and Retrieval Logic ---
    if selected_passage_id and selected_question_index and selected_model:
        if st.button("Run Evaluation", type="primary"):
            # Clear previous results before running a new evaluation
            st.session_state.retrieved_passages = []
            st.session_state.scores = {}
            
            with st.spinner("Retrieving passages..."):
                payload = {
                    "passage_id": selected_passage_id,
                    "question_index": selected_question_index,
                    "model_name": selected_model
                }
                results = post_api_data("/get_model_based_passage_data", payload)
                if results is not None:
                    st.session_state.retrieved_passages = results
                    # Initialize scores for the new results
                    st.session_state.scores = {i: None for i in range(len(results))}

    st.divider()

    # --- UI: DISPLAY RETRIEVED RESULTS & SCORING ---
    if st.session_state.retrieved_passages:
        st.header("3. Score Retrieved Passages")
        
        # Ensure we don't try to score more than 3 passages, even if API returns more
        passages_to_score = st.session_state.retrieved_passages[:3]
        
        for i, passage in enumerate(passages_to_score):
            st.markdown(f"---")
            st.subheader(f"Retrieved Passage #{i+1} (ID: `{passage['passage_id']}`)")
            st.text_area(f"Passage #{i+1} Text", passage['passage_text'], height=150, disabled=True, key=f"text_{i}")
            
            # The key links the radio button to our session state
            score_selection = st.radio(
                "Score this passage:",
                options=SCORING_OPTIONS,
                index=None,
                key=f"score_{i}",
                horizontal=True
            )
            if score_selection:
                st.session_state.scores[i] = SCORING_MAP[score_selection]

        # --- Submission Logic ---
        st.divider()
        if st.button("Submit Evaluation Results"):
            # Validate that all displayed passages have been scored
            all_scored = all(st.session_state.scores.get(i) is not None for i in range(len(passages_to_score)))
            
            if not all_scored:
                st.warning("Please score all retrieved passages before submitting.")
            else:
                # Prepare payload for submission
                submission_payload = {
                    "model_name": selected_model,
                    "passage_id": selected_passage_id,
                    "query_index": selected_question_index,
                }
                
                # Dynamically create p_val and p_score fields, padding with defaults if fewer than 3 results
                for i in range(3):
                    if i < len(passages_to_score):
                        submission_payload[f"p{i+1}_val"] = str(passages_to_score[i]['passage_id'])
                        submission_payload[f"p{i+1}_score"] = st.session_state.scores[i]
                    else:
                        submission_payload[f"p{i+1}_val"] = "N/A"
                        submission_payload[f"p{i+1}_score"] = 0 # Use 0 or another indicator for no passage
                
                with st.spinner("Saving results..."):
                    save_response = post_api_data("/save_evaluation_result", submission_payload)
                    if save_response and save_response.get("status") == "success":
                        st.success("✅ Evaluation successfully saved! You can now select a new query or model.")
                        # Clear state to prepare for the next run
                        st.session_state.retrieved_passages = []
                        st.session_state.scores = {}
                    else:
                        st.error("Failed to save evaluation results. Please check the API server logs.")

if __name__ == "__main__":
    main()