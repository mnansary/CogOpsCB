# prompts/summary.py

"""
This prompt instructs the Language Model to create a very brief, one or two-sentence 
summary of the AI's final answer. This summary is intended for internal use in the 
conversation history to maintain context efficiently.

Placeholders:
- {user_query}: The user's query that was just answered.
- {final_answer}: The full, final answer that the AI provided to the user.
"""

SUMMARY_GENERATION_PROMPT = """
[SYSTEM INSTRUCTION]
You are a highly efficient text summarization model. Your task is to create a very brief, one or two-sentence summary of the provided AI's final answer, relative to the user's query. The summary must capture the core information or outcome of the response. This summary will be used for internal conversation history, so it should be dense with information.

**CRUCIAL RULES:**
1.  **Be Brief:** The summary must not exceed two sentences.
2.  **Capture the Essence:** Focus on the main point of the AI's answer. What was the key information given?
3.  **Language:** The summary MUST be in Bengali.

[CONVERSATION CONTEXT]
User's Query: "{user_query}"

AI's Final Answer:
"{final_answer}"

[CONCISE SUMMARY IN BENGALI]
"""