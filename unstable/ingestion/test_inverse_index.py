# test_search.py

import argparse
import logging
import os
import sys
import yaml
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

def load_config(config_path):
    """Loads the YAML configuration file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            logging.info(f"Loading configuration from: {config_path}")
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"Configuration file not found at: {config_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error loading or parsing configuration file: {e}")
        sys.exit(1)

def create_es_client(es_host):
    """Establishes and verifies a connection to Elasticsearch."""
    logging.info(f"Connecting to Elasticsearch at {es_host}...")
    try:
        client = Elasticsearch(es_host)
        if not client.ping():
            raise ConnectionError("Connection failed. The ping was unsuccessful.")
        logging.info("✅ Elasticsearch connection successful!")
        return client
    except Exception as e:
        logging.error(f"❌ Failed to connect to Elasticsearch: {e}")
        sys.exit(1)

def run_search(client, query_text, config):
    """
    Constructs and executes a multi_match query against the specified index
    and prints the formatted results.
    """
    index_name = config['elasticsearch']['index_name']
    fields_config = config['elasticsearch']['fields']

    # Check if the index exists before querying
    if not client.indices.exists(index=index_name):
        logging.error(f"Index '{index_name}' does not exist. Please run the ingestion script first.")
        return

    # Dynamically construct the list of fields to search over, with boosts.
    # Boosting makes matches in certain fields (like our stemmed field) more important.
    search_fields = [
        f"{fields_config['english_analyzed']}^2",      # Boost English matches
        fields_config['bengali_analyzed'],             # Standard Bengali matches
        f"{fields_config['bengali_stemmed']}^4"         # Highest boost for custom stemmed field
    ]

    # This is the core multi-match query. It searches the user's text
    # against all our specified fields and uses the best score (BM25).
    query_body = {
        "query": {
            "multi_match": {
                "query": query_text,
                "fields": search_fields,
                "type": "best_fields"
            }
        }
    }

    # --- Print Query Information ---
    print("\n" + "="*80)
    print(f"Executing Query: '{query_text}'")
    print(f"Searching fields: {search_fields}")
    print("="*80)

    try:
        response = client.search(index=index_name, body=query_body, size=3) # Get top 3 results

        hits = response['hits']['hits']
        if not hits:
            print("--- No results found. ---")
            return

        print(f"Found {response['hits']['total']['value']} results. Showing top {len(hits)}:\n")
        for i, hit in enumerate(hits):
            score = hit['_score']
            # Display the original, clean text from the raw field for readability
            passage_text = hit['_source'][fields_config['raw']]
            print(f"  Result {i+1} | Score: {score:.4f}")
            print(f"  Text: {passage_text}\n")

    except Exception as e:
        logging.error(f"An error occurred during search: {e}")


def main():
    """Main entry point for the test script."""
    parser = argparse.ArgumentParser(
        description="Test search queries against a configured Elasticsearch index."
    )
    parser.add_argument(
        '--config',
        type=str,
        required=True,
        help="Path to the inverse_index.yaml configuration file."
    )
    args = parser.parse_args()

    # --- Load Environment and Configuration ---
    load_dotenv()
    es_host = os.getenv("ES_HOST")
    if not es_host:
        logging.error("ES_HOST environment variable not found. Please create a .env file.")
        sys.exit(1)

    config = load_config(args.config)
    es_client = create_es_client(es_host)

    # --- Define Query Variations ---
    test_queries = {
        "✅ Vanilla Query": "এন আই ডি কার্ড করার প্রক্রিয়া কি?",
        "✅ Personal Query": "আমার চাচা অসুস্থ, আমি রাজশাহীতে আছি। জরুরি অ্যাম্বুলেন্সের নাম্বার লাগবে।",
        "❌ Non-Service Query": "আজকে আমার দিনটা খুব খারাপ গেলো",
        "⚠️ Ambiguous Query": "আমি ফর্ম পূরণ করতে চাই",
        "✅ Compound Query": "আমি পাসপোর্ট বানানোর নিয়ম জানতে চাই আর অফিসের ঠিকানা কোথায়?",
        "✅ Mixed-Language Query": "How to get birth certificate online?"
    }

    # --- Run Tests ---
    for category, query in test_queries.items():
        print(f"\n\n{'='*20} Testing Category: {category} {'='*20}")
        run_search(es_client, query, config)

if __name__ == "__main__":
    main()