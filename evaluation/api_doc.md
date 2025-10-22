# Retrieval Evaluation API Documentation

## **Overview**

This API provides a suite of endpoints designed to support the human evaluation of a hybrid retrieval system. It allows a client application (like a Streamlit dashboard) to fetch source passages and questions, execute different retrieval models against them, and save the human-generated evaluation results to a persistent data store.

**Base URL**: `http://127.0.0.1:9051`

**CORS Policy**: The API is configured with a permissive Cross-Origin Resource Sharing (CORS) policy (`allow_origins=["*"]`), allowing requests from any domain. This is suitable for development environments.

---

## **General Concepts**

### Model Naming Convention

The `model_name` parameter is the core of the retrieval logic and follows a specific pattern: `<prefix>_<part1>_<part2>...`

*   **Prefix (`qwen3_` or `embGemma_`):** This determines the query processing strategy.
    *   `qwen3_`: **Intelligent Formatting.** The user's query is first sent to an LLM-based "Query Formatter" to generate a structured set of queries (`proposition`, `summary`, `question`) optimized for retrieval.
    *   `embGemma_`: **Direct Retrieval.** The raw user query is used directly for all specified parts without any LLM transformation.

*   **Parts (`prop`, `summ`, `ques`):** This specifies which retrieval pipelines (and corresponding vector collections) to use.
    *   `prop`: Uses the `proposition` query against the `PropositionsDB`.
    *   `summ`: Uses the `summary` query against the `SummariesDB`.
    *   `ques`: Uses the `question` query against the `QuestionsDB`.
    *   *Example*: `qwen3_ques_prop` will use the intelligent formatter to generate a question and a proposition, then search both the `QuestionsDB` and `PropositionsDB`.

### Scoring Convention

When submitting evaluation results via the `/save_evaluation_result` endpoint, the integer scores should be mapped as follows:
*   `1`: **Exact Match** - The retrieved passage is the original source passage for the query.
*   `2`: **Relevant** - The retrieved passage is not the exact source, but it correctly and relevantly answers the query.
*   `3`: **Irrelevant** - The retrieved passage does not answer the query.
*   `0`: **Placeholder** - Used to indicate that no passage was retrieved for a given position (e.g., for `p3_score` if only two passages were returned).

---

## **API Endpoints**

### Data Access Endpoints

These endpoints are used to fetch the source data for building the evaluation interface.

#### 1. Get Passage List

Returns a numerically sorted list of all available passage IDs.

*   **Endpoint:** `GET /get_passage_list`
*   **Method:** `GET`
*   **Description:** Fetches all `.json` filenames from the data directory to populate a list of all passages that can be evaluated.
*   **Parameters:** None
*   **Successful Response (200 OK):**
    *   **Content-Type:** `application/json`
    *   **Body:** A JSON array of numeric strings, sorted numerically.
    ```json
    [
      "1",
      "2",
      "10",
      "42",
      "101"
    ]
    ```
*   **Error Responses:**
    *   `500 Internal Server Error`: If the server's data directory is missing or misconfigured.

---

#### 2. Get Question List for a Passage

Returns the full passage text and a list of 1-based indices for its associated questions.

*   **Endpoint:** `GET /get_question_list`
*   **Method:** `GET`
*   **Description:** Retrieves the content of a specific passage, necessary for displaying the source text and the list of available queries.
*   **Query Parameters:**

| Parameter | Type | Required | Example | Description |
| :--- | :--- | :--- | :--- | :--- |
| `passage_id` | string | Yes | `"42"` | The numeric string ID of the passage to retrieve. |

*   **Successful Response (200 OK):**
    *   **Content-Type:** `application/json`
    *   **Body:**
    ```json
    {
      "passage": "স্মার্ট কার্ড বা স্মার্ট এনআইডি পেতে প্রথমে...",
      "question_indexes": [1, 2, 3, 4]
    }
    ```
*   **Error Responses:**
    *   `404 Not Found`: If the requested `passage_id` does not exist.
    *   `500 Internal Server Error`: If the JSON file for the passage is corrupted.

---

#### 3. Get Specific Question

Returns the text of a single question from a passage.

*   **Endpoint:** `GET /get_question`
*   **Method:** `GET`
*   **Description:** Fetches the exact text of a query that will be used in the retrieval process.
*   **Query Parameters:**

| Parameter | Type | Required | Example | Description |
| :--- | :--- | :--- | :--- | :--- |
| `passage_id` | string | Yes | `"42"` | The numeric string ID of the passage. |
| `question_index` | integer | Yes | `3` | The **1-based** index of the question. |


*   **Successful Response (200 OK):**
    *   **Content-Type:** `application/json`
    *   **Body:**
    ```json
    {
      "question": "আমার স্মার্ট কার্ড তৈরি হয়েছে কিনা জানি না। এটা জানার কি কোনো সুযোগ আছে?"
    }
    ```
*   **Error Responses:**
    *   `404 Not Found`: If the `passage_id` does not exist.
    *   `400 Bad Request`: If `question_index` is `0`, negative, or out of bounds.

---

### Retrieval & Evaluation Endpoints

These endpoints drive the core evaluation workflow.

#### 4. Get Model List

Generates and returns a list of all valid model names.

*   **Endpoint:** `GET /get_models`
*   **Method:** `GET`
*   **Description:** Provides a comprehensive list of all possible model combinations for the UI.
*   **Parameters:** None
*   **Successful Response (200 OK):**
    *   **Content-Type:** `application/json`
    *   **Body:** A sorted JSON array of strings.
    ```json
    [
      "embGemma_prop",
      "embGemma_prop_ques",
      "embGemma_prop_summ",
      "...",
      "qwen3_prop",
      "qwen3_prop_ques",
      "..."
    ]
    ```

---

#### 5. Get Model-Based Passage Data

The primary retrieval endpoint. Executes a retrieval process based on a model and source query.

*   **Endpoint:** `POST /get_model_based_passage_data`
*   **Method:** `POST`
*   **Description:** This is the core function. It takes a source query (identified by `passage_id` and `question_index`) and a `model_name`, performs conditional query formatting, runs retrieval, and returns the top relevant passages.
*   **Request Body:**
    *   **Content-Type:** `application/json`
    ```json
    {
      "passage_id": "42",
      "question_index": 3,
      "model_name": "qwen3_ques_prop"
    }
    ```
*   **Successful Response (200 OK):**
    *   **Content-Type:** `application/json`
    *   **Body:** A JSON array of retrieved passage objects, ordered by relevance. The array will be empty (`[]`) if no passages are found. The `passage_id` in the response is an integer.
    ```json
    [
      {
        "passage_id": 105,
        "passage_text": "জাতীয় পরিচয়পত্র নবায়নের জন্য প্রথমে অনলাইনে আবেদন করতে হবে..."
      },
      {
        "passage_id": 108,
        "passage_text": "অনলাইনে আবেদনের পর আপনাকে নিকটস্থ নির্বাচন অফিসে যোগাযোগ করতে হবে..."
      }
    ]
    ```
*   **Error Responses:**
    *   `400 Bad Request`: If `model_name` is invalid or if the retriever's strict validation fails (e.g., a required query key is missing).
    *   `404 Not Found`: If the source `passage_id` does not exist.
    *   `500 Internal Server Error`: If a critical error occurs during query formatting or retrieval.
    *   `503 Service Unavailable`: If the API's backend models failed to initialize on startup.

---

#### 6. Save Evaluation Result

Saves the human-provided scores for a retrieval run to a CSV file on the server.

*   **Endpoint:** `POST /save_evaluation_result`
*   **Method:** `POST`
*   **Description:** Persists the results of a single evaluation run. This endpoint is thread-safe and appends a new row to the evaluation CSV file.
*   **Request Body:**
    *   **Content-Type:** `application/json`
    *   **`p*_val`** fields should be the numeric string ID of the retrieved passage, or `"N/A"` if no passage was returned for that position.
    ```json
    {
      "model_name": "qwen3_ques_prop",
      "passage_id": "42",
      "query_index": 3,
      "p1_val": "105",
      "p1_score": 2,
      "p2_val": "108",
      "p2_score": 3,
      "p3_val": "N/A",
      "p3_score": 0
    }
    ```
*   **Successful Response (200 OK):**
    *   **Content-Type:** `application/json`
    *   **Body:**
    ```json
    {
      "status": "success",
      "message": "Evaluation result saved."
    }
    ```
*   **Error Responses:**
    *   `422 Unprocessable Entity`: If the request body is missing fields or has incorrect data types (e.g., `p1_score` is a string instead of an integer).
    *   `500 Internal Server Error`: If the server fails to write to the CSV file.