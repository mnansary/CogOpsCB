import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from typing import Generator, Any, Type, TypeVar, List

from pydantic import BaseModel, Field

# Load environment variables from a .env file
load_dotenv()

# Generic type variable for Pydantic models for clean type hinting.
PydanticModel = TypeVar("PydanticModel", bound=BaseModel)


class LLMService:
    """
    A synchronous client for OpenAI-compatible APIs using the 'openai' library.

    This service supports standard, streaming, and structured (Pydantic-validated)
    responses. Structured output is achieved using the 'response_format'
    parameter for broad model compatibility.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str
    ):
        """
        Initializes the client using the OpenAI library.

        Args:
            api_key (str): The API key for authentication.
            model (str): The name of the model to use for requests.
            base_url (str): The base URL of the API service.
        """
        if not api_key:
            raise ValueError("API key cannot be empty. Please set it in your .env file or pass it directly.")
        
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        
        print(f"✅ LLMService initialized for model '{self.model}' using 'response_format' for structured output.")

    def invoke(self, prompt: str, **kwargs: Any) -> str:
        """
        Sends a request for a single, complete response (non-streaming).
        """
        messages = [{"role": "user", "content": prompt}]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"\n[Error] An error occurred during invoke: {e}")
            raise

    def stream(self, prompt: str, **kwargs: Any) -> Generator[str, None, None]:
        """
        Connects to the streaming endpoint and yields text chunks as they arrive.
        """
        messages = [{"role": "user", "content": prompt}]
        
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                **kwargs
            )
            for chunk in stream:
                content_chunk = chunk.choices[0].delta.content
                if content_chunk:
                    yield content_chunk
        except Exception as e:
            print(f"\n[Error] An error occurred during stream: {e}")
            raise

    def invoke_structured(
        self,
        prompt: str,
        response_model: Type[PydanticModel],
        **kwargs: Any
    ) -> PydanticModel:
        """
        Sends a request for a structured response validated by a Pydantic model.

        This method uses the `response_format={"type": "json_object"}` feature.
        It constructs a detailed prompt that includes the JSON schema of the
        Pydantic model, instructing the LLM to generate a conforming JSON object.

        Args:
            prompt (str): The user's core prompt/question.
            response_model (Type[PydanticModel]): The Pydantic model to validate against.
            **kwargs: Additional keyword arguments to pass to the API.

        Returns:
            PydanticModel: An instance of the response_model populated with the LLM's response.
        """
        # 1. Generate the JSON schema from the Pydantic model.
        schema = json.dumps(response_model.model_json_schema(), indent=2)

        # 2. Engineer a new prompt that includes the original prompt and instructions.
        structured_prompt = f"""
        Given the following request:
        ---
        {prompt}
        ---
        Your task is to provide a response as a single, valid JSON object.
        This JSON object must strictly adhere to the following JSON Schema.
        Do not include any extra text, explanations, or markdown formatting (like ```json) outside of the JSON object itself.

        JSON Schema:
        {schema}
        """

        messages = [{"role": "user", "content": structured_prompt}]

        try:
            # 3. Call the API with the 'response_format' parameter.
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                **kwargs
            )

            # 4. The entire response content is the JSON string.
            # <<< FIX: Access the first item in the 'choices' list using >>>
            json_response_str = response.choices[0].message.content
            if not json_response_str:
                raise ValueError("The model returned an empty response.")

            # 5. Parse and validate the JSON string using the Pydantic model.
            return response_model.model_validate_json(json_response_str)

        except Exception as e:
            print(f"\n[Error] An error occurred during structured invoke: {e}")
            raise


if __name__ == '__main__':

    # --- Example Usage ---

    # Define a Pydantic model for the desired structured output
    class Recipe(BaseModel):
        recipe_name: str = Field(description="The title of the recipe.")
        prep_time_minutes: int = Field(description="Time required for preparation in minutes.")
        ingredients: List[str] = Field(description="A list of all necessary ingredients.")
        is_vegetarian: bool = Field(description="True if the recipe contains no meat, false otherwise.")

    # Initialize the service using your API key from the .env file
    api_key = os.getenv("VLLM_MEDIUM_API_KEY")
    model   = os.getenv("VLLM_MEDIUM_MODEL_NAME")
    base_url = os.getenv("VLLM_MEDIUM_BASE_URL")
    if not api_key:
        print("Error: VLLM_MEDIUM_API_KEY not found in .env file.")
    else:
        # Use a model known to support JSON mode, e.g., gpt-4o, gpt-4-turbo,
        # or a compatible open-source model.
        llm_service = LLMService(api_key=api_key, model=model, base_url=base_url)

        # --- Example 1: Standard `invoke` call ---
        print("\n--- 1. Standard Invoke Call ---")
        try:
            response = llm_service.invoke("Who discovered penicillin?")
            print(f"Response:\n{response}")
        except Exception as e:
            print(f"An error occurred: {e}")
            
        # --- Example 2: Structured Invoke Call using JSON Mode ---
        print("\n--- 2. Structured Invoke Call ---")
        try:
            structured_prompt = "Generate a simple recipe for a classic Margherita pizza. It takes about 20 minutes to prepare."
            print(f"Prompt: {structured_prompt}")
            
            recipe_data = llm_service.invoke_structured(structured_prompt, Recipe)
            
            print(f"\nSuccessfully parsed response into a '{type(recipe_data).__name__}' object:")
            print(recipe_data.model_dump_json(indent=2))
            
            print(f"\nAccessing data programmatically:")
            print(f"  Recipe: {recipe_data.recipe_name}")
            print(f"  Prep Time: {recipe_data.prep_time_minutes} minutes")
            print(f"  Vegetarian: {'Yes' if recipe_data.is_vegetarian else 'No'}")
            print(f"  First ingredient: {recipe_data.ingredients}")
            
        except Exception as e:
            print(f"An error occurred: {e}")

        # --- Example 3: Streaming call ---
        print("\n--- 3. Streaming Call ---")
        try:
            stream_prompt = "Write a short, 50-word story about a robot who discovers music for the first time."
            print(f"Prompt: {stream_prompt}\n")
            print("Streaming Response:")
            # Iterate over the generator and print each chunk as it arrives.
            for chunk in llm_service.stream(stream_prompt):
                print(chunk, end="", flush=True)
            print("\n") # Add a newline after the stream is complete
        except Exception as e:
            print(f"An error occurred during stream: {e}")