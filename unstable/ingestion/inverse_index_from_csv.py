# ingest_data.py

import argparse
import logging
import os
import sys
import yaml
import pandas as pd
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
import re

# Using the 'bangla-stemmer' library by Fatick DevStudio.
from bangla_stemmer.stemmer import stemmer as fatick_stemmer

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

def create_index_with_mapping(client, index_name, fields_config):
    """
    Creates an Elasticsearch index. If the index already exists, it is
    deleted first to ensure a clean slate.
    """
    # --- THIS IS THE CRUCIAL SECTION ---
    # Check if the index specified in the YAML config already exists.
    if client.indices.exists(index=index_name):
        # If it exists, log a warning and delete it. This is essential for
        # ensuring that any changes to the mapping are applied correctly
        # on every run.
        logging.warning(f"Index '{index_name}' already exists. Deleting it for a fresh start.")
        client.indices.delete(index=index_name)
    # --- END OF SECTION ---

    # Dynamically build the properties mapping from the YAML config
    properties = {
        fields_config['raw']: {"type": "keyword"},
        fields_config['english_analyzed']: {"type": "text", "analyzer": "english"},
        fields_config['bengali_analyzed']: {"type": "text", "analyzer": "bengali"},
        fields_config['bengali_stemmed']: {"type": "text", "analyzer": "whitespace"}
    }
    
    index_body = {"mappings": {"properties": properties}}

    try:
        logging.info(f"Creating new index '{index_name}' with advanced mapping...")
        client.indices.create(index=index_name, body=index_body)
        logging.info("✅ Index created successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to create index: {e}")
        sys.exit(1)

def stem_bengali_text(text, stemmer_instance):
    """Pre-stems Bengali text using the specified external library."""
    if not isinstance(text, str):
        return ""
    words = re.findall(r'[\u0980-\u09FF\w]+', text)
    stemmed_words = [stemmer_instance.stem(word) for word in words]
    return " ".join(stemmed_words)

def generate_bulk_actions(df, config):
    """
    Generator function that pre-processes data and yields documents for bulk indexing.
    """
    stemmer_instance = fatick_stemmer.BanglaStemmer()
    logging.info(f"Preparing and stemming {len(df)} documents for indexing...")

    id_col = config['data_source']['id_column']
    text_col = config['data_source']['source_text_column']
    index_name = config['elasticsearch']['index_name']
    fields = config['elasticsearch']['fields']
    
    for _, row in df.iterrows():
        source_text = row[text_col]
        stemmed_text = stem_bengali_text(source_text, stemmer_instance)

        document = {
            fields['raw']: source_text,
            fields['english_analyzed']: source_text,
            fields['bengali_analyzed']: source_text,
            fields['bengali_stemmed']: stemmed_text,
        }
        
        yield {
            "_index": index_name,
            "_id": row[id_col],
            "_source": document,
        }

def run_ingestion(config, client):
    """Orchestrates the data reading and bulk ingestion process."""
    try:
        csv_path = config['data_source']['csv_path']
        id_col = config['data_source']['id_column']
        text_col = config['data_source']['source_text_column']

        logging.info(f"Reading data from CSV file: {csv_path}")
        df = pd.read_csv(csv_path)
        
        df.dropna(subset=[text_col], inplace=True)
        df[id_col] = df[id_col].astype(str)

        logging.info("Starting bulk ingestion process. This may take a while...")
        success, failed = bulk(client, generate_bulk_actions(df, config), raise_on_error=False, chunk_size=500)
        
        logging.info("✅ Ingestion complete.")
        logging.info(f"   Successfully indexed documents: {success}")
        if failed:
            logging.warning(f"   Failed to index documents: {len(failed)}")

    except FileNotFoundError:
        logging.error(f"❌ Error: The file was not found at '{csv_path}'. Please check your YAML config.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"❌ An unexpected error occurred during ingestion: {e}")
        sys.exit(1)

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Ingest mixed-language data into Elasticsearch.")
    parser.add_argument(
        '--config',
        type=str,
        required=True,
        help="Path to the inverse_index.yaml configuration file."
    )
    args = parser.parse_args()

    load_dotenv()
    es_host = os.getenv("ES_HOST")
    if not es_host:
        logging.error("ES_HOST environment variable not found. Please create a .env file.")
        sys.exit(1)

    config = load_config(args.config)

    es_client = create_es_client(es_host)
    create_index_with_mapping(
        client=es_client,
        index_name=config['elasticsearch']['index_name'],
        fields_config=config['elasticsearch']['fields']
    )
    run_ingestion(config, es_client)

if __name__ == "__main__":
    main()