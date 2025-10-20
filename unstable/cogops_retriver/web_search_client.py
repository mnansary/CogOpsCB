# FILE: cogops/retriver/web_search_client.py

import httpx
import logging
from typing import List, Dict, Any

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class WebSearchClient:
    """
    An asynchronous client to interact with the external search_and_crawl API.

    This client is responsible for sending a query to the API, which then
    searches for relevant government websites, crawls them, and returns
    cleaned content.
    """
    def __init__(self, api_url: str, timeout: int = 20):
        """
        Initializes the client with the full URL of the search_and_crawl service endpoint.

        Args:
            api_url (str): The full URL of the search and crawl API endpoint
                           (e.g., "http://localhost:9234/search-and-crawl").
            timeout (int): The total timeout for the request in seconds.
        """
        if not api_url:
            raise ValueError("The API URL for the WebSearchClient cannot be empty.")

        self.api_url = api_url
        self.timeout = httpx.Timeout(timeout)
        logging.info(f"✅ WebSearchClient initialized for API at: {self.api_url}")

    async def search_and_crawl(self, query: str) -> List[Dict[str, Any]]:
        """
        Sends a query to the search_and_crawl API and returns the crawled content.

        Args:
            query (str): The search query to be processed.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, where each dictionary
                                  represents a crawled page with "title", "url",
                                  and "content". Returns an empty list on failure.
        """
        payload = {"query": query}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logging.info(f"Sending query to WebSearchClient: '{query}' at {self.api_url}")
                # The full URL is now used directly
                response = await client.post(self.api_url, json=payload)

                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                if not results:
                    logging.warning(f"WebSearchClient returned no results for query: '{query}'")
                else:
                    logging.info(f"WebSearchClient successfully returned {len(results)} results.")

                return results

        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error occurred when calling WebSearchClient: {e.response.status_code} - {e.response.text}")
            return []
        except httpx.RequestError as e:
            logging.error(f"Network request error occurred when calling WebSearchClient: {e}")
            return []
        except Exception as e:
            logging.error(f"An unexpected error occurred in WebSearchClient: {e}", exc_info=True)
            return []