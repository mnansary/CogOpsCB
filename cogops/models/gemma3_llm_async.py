import os
import json
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI # <-- Import the Async client
from typing import Generator, Any, Type, TypeVar, List, AsyncGenerator

from pydantic import BaseModel, Field

load_dotenv()

PydanticModel = TypeVar("PydanticModel", bound=BaseModel)

class AsyncLLMService:
    """
    An ASYNCHRONOUS client for OpenAI-compatible APIs.
    Supports standard, streaming, and structured (Pydantic-validated) responses.
    """
    def __init__(self, api_key: str, model: str, base_url: str):
        if not api_key:
            raise ValueError("API key cannot be empty.")
        
        self.model = model
        # --- Use the AsyncOpenAI client ---
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        
        print(f"✅ AsyncLLMService initialized for model '{self.model}'.")

    async def invoke(self, prompt: str, **kwargs: Any) -> str:
        messages = [{"role": "user", "content": prompt}]
        try:
            # --- Use 'await' for the async call ---
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"\n[Error] An error occurred during invoke: {e}")
            raise

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncGenerator[str, None]:
        messages = [{"role": "user", "content": prompt}]
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                **kwargs
            )
            async for chunk in stream: # <-- Use 'async for'
                content_chunk = chunk.choices[0].delta.content
                if content_chunk:
                    yield content_chunk
        except Exception as e:
            print(f"\n[Error] An error occurred during stream: {e}")
            raise

    async def invoke_structured(
        self,
        prompt: str,
        response_model: Type[PydanticModel],
        **kwargs: Any
    ) -> PydanticModel:
        schema = json.dumps(response_model.model_json_schema(), indent=2)
        structured_prompt = f"""
        Given the following request:
        ---
        {prompt}
        ---
        Your task is to provide a response as a single, valid JSON object that strictly adheres to the following JSON Schema.
        Do not include any extra text or markdown formatting.

        JSON Schema:
        {schema}
        """
        messages = [{"role": "user", "content": structured_prompt}]
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                **kwargs
            )
            json_response_str = response.choices[0].message.content
            if not json_response_str:
                raise ValueError("The model returned an empty response.")
            return response_model.model_validate_json(json_response_str)
        except Exception as e:
            print(f"\n[Error] An error occurred during structured invoke: {e}")
            raise