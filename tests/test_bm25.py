from elasticsearch import Elasticsearch

# 1. Connect to your insecure Elasticsearch instance
client = Elasticsearch("http://localhost:9200")

# --- Indexing ---
# Sample data mirroring your project's needs
passages = [
    {"passage_id": 1, "text_content": "To check your smart card status, send an SMS to 105."},
    {"passage_id": 2, "text_content": "The online portal for smart card services is services.nidw.gov.bd."},
    {"passage_id": 3, "text_content": "You can check the application status for your NID card online."}
]

print("Indexing sample passages...")
# Index each document into an index named 'passage_index'
for doc in passages:
    client.index(
        index="passage_index",
        id=doc["passage_id"],
        document={"text": doc["text_content"]},
        # This makes the document immediately available for searching
        refresh="wait_for" 
    )
print("Indexing complete.")


# --- Searching (This is where BM25 is automatically used) ---
query_text = "check smart card status"
print(f"\nSearching for: '{query_text}'")

# A standard 'match' query uses the BM25 algorithm by default
response = client.search(
    index="passage_index",
    query={
        "match": {
            "text": query_text
        }
    }
)

print("\n--- Search Results (Ranked by BM25 Score) ---")
for hit in response['hits']['hits']:
    # The '_score' is the relevance score calculated by BM25
    score = hit['_score'] 
    passage_text = hit['_source']['text']
    print(f"Score: {score:.4f} | Text: {passage_text}")

# Clean up the index
# client.indices.delete(index="passage_index")