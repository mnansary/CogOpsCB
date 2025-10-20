
RERANK_PROMPT_TEMPLATE = """
You are an expert relevance evaluation assistant. Your task is to determine if the provided PASSAGE is relevant for answering the user's intent, considering the CONVERSATION HISTORY and the specific SEARCH QUERY used for retrieval.

Your evaluation must result in a score of 1, 2, or 3.
1: The passage directly and completely answers the user's query.
2: The passage is on-topic and partially relevant, but not a complete answer.
3: The passage is unrelated to the user's query.

---
[EXAMPLE 1]
CONVERSATION HISTORY:
No conversation history yet.

USER QUERY (Natural Language):
আমার এনআইডি কার্ড হারিয়ে গেছে, এখন কি করব?

SEARCH QUERY (Used for Retrieval):
হারিয়ে যাওয়া জাতীয় পরিচয়পত্র উত্তোলনের নিয়মাবলী

PASSAGE TO EVALUATE:
জাতীয় পরিচয়পত্র হারিয়ে গেলে নিকটতম থানায় জিডি করে জিডির মূল কপিসহ সংশ্লিষ্ট উপজেলা/থানা নির্বাচন অফিসে আবেদন করতে হবে। আবেদন ফর্মের সাথে নির্দিষ্ট ফি জমা দিতে হবে।

RESPONSE:
{{
  "score": 1,
  "reasoning": "The passage directly answers the user's question about what to do for a lost NID card by stating the need for a GD and applying at the election office."
}}
---

[EXAMPLE 2]
CONVERSATION HISTORY:
No conversation history yet.

USER QUERY (Natural Language):
আমার এনআইডি কার্ড হারিয়ে গেছে, এখন কি করব?

SEARCH QUERY (Used for Retrieval):
হারিয়ে যাওয়া জাতীয় পরিচয়পত্র উত্তোলনের নিয়মাবলী

PASSAGE TO EVALUATE:
জাতীয় পরিচয়পত্র নিবন্ধনের সময় প্রদত্ত স্লিপটি হারিয়ে গেলে, থানায় জিডি করে জিডির মূল কপিসহ সংশ্লিষ্ট উপজেলা/থানা নির্বাচন অফিসে যোগাযোগ করতে হবে। বায়োমেট্রিক যাচাইয়ের পর কার্ড সরবরাহ করা হবে।

RESPONSE:
{{
  "score": 2,
  "reasoning": "The passage is about a lost NID slip, which is related to the user's query about a lost NID card, but it is not the same thing. Therefore, it is only partially relevant."
}}
---

[EXAMPLE 3]
CONVERSATION HISTORY:
No conversation history yet.

USER QUERY (Natural Language):
আমার এনআইডি কার্ড হারিয়ে গেছে, এখন কি করব?

SEARCH QUERY (Used for Retrieval):
হারিয়ে যাওয়া জাতীয় পরিচয়পত্র উত্তোলনের নিয়মাবলী

PASSAGE TO EVALUATE:
আজ আমরা আপনাদের জন্য নিয়ে এসেছি মজাদার গরুর মাংসের কালা ভুনা রেসিপি। এই রেসিপিটি অনুসরণ করে আপনি সহজেই ঘরেই তৈরি করতে পারবেন এই ঐতিহ্যবাহী খাবারটি।

RESPONSE:
{{
  "score": 3,
  "reasoning": "The passage is completely unrelated to the user's query about a lost NID card. It is about a cooking recipe."
}}
---

[TASK]
CONVERSATION HISTORY:
{history_str}

USER QUERY (Natural Language):
{user_query}

SEARCH QUERY (Used for Retrieval):
{search_query}

PASSAGE TO EVALUATE:
{passage_text}

RESPONSE:

"""