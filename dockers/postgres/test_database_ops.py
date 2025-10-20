import pandas as pd
from datetime import date
from loguru import logger
import sys

from cogops.retriver.db import SQLDatabaseManager
from cogops.utils.db_config import get_postgres_config

# Load the configuration once when the module is imported
POSTGRES_CONFIG = get_postgres_config()

def run_tests():
    """
    Runs a series of tests to validate the SQLDatabaseManager functionality.
    """
    # --- Setup ---
    logger.info("Initializing Database Manager for testing...")
    
    # Add 'echo': True to see the generated SQL queries in your console
    # db_config_with_echo = {**POSTGRES_CONFIG, 'echo': True}
    # db_manager = SQLDatabaseManager(db_config_with_echo)
    
    db_manager = SQLDatabaseManager(POSTGRES_CONFIG)
    
    logger.info("--- Starting Database Operations Test ---")

    # --- 0. Initial Cleanup ---
    # Ensure the table is empty before starting to avoid conflicts from previous runs
    logger.info("\n[Phase 0] Clearing all existing entries for a clean test...")
    all_data = db_manager.select_passages()
    if not all_data.empty:
        for passage_id in all_data['passage_id'].tolist():
            db_manager.delete_passages({'passage_id': passage_id})
    logger.info("Table cleared.")
    
    # --- 1. Test INSERT ---
    logger.info("\n[Phase 1] Testing INSERT operations...")
    passages_to_insert = [
        {'passage_id': 1, 'topic': 'AI Ethics', 'text': 'The study of ethical issues in AI.', 'date': date(2024, 1, 10)},
        {'passage_id': 2, 'topic': 'Quantum Computing', 'text': 'A new paradigm of computation.', 'date': date(2024, 2, 20)},
        {'passage_id': 3, 'topic': 'Web Development', 'text': 'The latest trends in frontend frameworks.', 'date': date(2024, 3, 15)},
    ]
    db_manager.insert_passages(passages_to_insert)
    logger.info("Data inserted.")

    # --- 2. Test SELECT (All) ---
    logger.info("\n[Phase 2] Testing SELECT all...")
    all_passages = db_manager.select_passages()
    print("All passages after insert:")
    print(all_passages)
    assert len(all_passages) == 3, "SELECT all check failed!"
    logger.info("SELECT all test PASSED.")

    # --- 3. Test SELECT BY IDS ---
    logger.info("\n[Phase 3] Testing SELECT BY IDS for passages 1 and 3...")
    selected_passages = db_manager.select_passages_by_ids([1, 3])
    print("Selected passages (1, 3):")
    print(selected_passages)
    assert len(selected_passages) == 2, "SELECT BY IDS check failed!"
    assert all(pid in [1, 3] for pid in selected_passages['passage_id']), "Incorrect IDs returned!"
    logger.info("SELECT BY IDS test PASSED.")

    # --- 4. Test UPDATE ---
    logger.info("\n[Phase 4] Testing UPDATE on passage_id 2...")
    update_data = [{'passage_id': 2, 'topic': 'Advanced Quantum Computing', 'url': 'http://example.com/quantum'}]
    db_manager.update_passages(condition_columns=['passage_id'], update_array=update_data)
    
    updated_passage = db_manager.select_passages({'passage_id': 2})
    print("Passage 2 after update:")
    print(updated_passage)
    assert updated_passage.iloc[0]['topic'] == 'Advanced Quantum Computing', "UPDATE check failed!"
    logger.info("UPDATE test PASSED.")

    # --- 5. Test UPSERT (for an existing ID) ---
    logger.info("\n[Phase 5] Testing UPSERT to update an existing passage (ID 1)...")
    # This should UPDATE passage 1 because the passage_id already exists
    upsert_update_data = [
        {'passage_id': 1, 'text': 'A revised text on AI ethics and societal impact.', 'date': date(2025, 1, 1)},
    ]
    db_manager.upsert_passages(insert_data=upsert_update_data, update_columns=['text', 'date'])

    upserted_passage = db_manager.select_passages({'passage_id': 1})
    print("Passage 1 after upsert (update):")
    print(upserted_passage)
    assert upserted_passage.iloc[0]['date'] == date(2025, 1, 1), "UPSERT (update) check failed!"
    logger.info("UPSERT (update) test PASSED.")

    # --- 6. Test UPSERT (for a new ID) ---
    logger.info("\n[Phase 6] Testing UPSERT to insert a new passage (ID 4)...")
    # This should INSERT a new passage because passage_id 4 does not exist
    upsert_insert_data = [
        {'passage_id': 4, 'topic': 'Blockchain', 'text': 'Decentralized ledger technology.', 'date': date(2024, 5, 5)},
    ]
    db_manager.upsert_passages(insert_data=upsert_insert_data, update_columns=['topic', 'text', 'date'])
    
    all_passages_after_upsert = db_manager.select_passages()
    print("All passages after upsert (insert):")
    print(all_passages_after_upsert)
    assert len(all_passages_after_upsert) == 4, "UPSERT (insert) check failed!"
    logger.info("UPSERT (insert) test PASSED.")

    # --- 7. Test DELETE ---
    logger.info("\n[Phase 7] Testing DELETE on passage_id 3...")
    db_manager.delete_passages({'passage_id': 3})
    
    passages_after_delete = db_manager.select_passages()
    print("All passages after deleting ID 3:")
    print(passages_after_delete)
    assert len(passages_after_delete) == 3, "DELETE check failed!"
    assert 3 not in passages_after_delete['passage_id'].values, "Deleted ID still present!"
    logger.info("DELETE test PASSED.")

    # --- 8. Final Cleanup ---
    logger.info("\n[Phase 8] Cleaning up all test entries...")
    remaining_ids = passages_after_delete['passage_id'].tolist()
    for pid in remaining_ids:
        db_manager.delete_passages({'passage_id': pid})
    
    final_check = db_manager.select_passages()
    assert final_check.empty, "Final cleanup failed!"
    logger.info("Table successfully cleared.")
    
    logger.info("\n--- ALL TESTS COMPLETED SUCCESSFULLY ---")


if __name__ == '__main__':
    run_tests()