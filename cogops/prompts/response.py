from pydantic import BaseModel, Field
from typing import List, Optional, Literal

Answerability = Literal[
    "FULLY_ANSWERABLE",
    "PARTIALLY_ANSWERABLE",
    "NOT_ANSWERABLE"
]

class ResponseStrategy(BaseModel):
    """Outlines the strategy for generating the final response to the user."""
    hyde_passage: str = Field(description="A hypothetical document snippet that would perfectly answer the query. MUST BE IN BENGALI.")
    answerability_prediction: Answerability = Field(..., description="Prediction of how well the database can answer the query.")
    response_plan: List[str] = Field(..., description="A step-by-step plan (in English) for the response generation model.")
