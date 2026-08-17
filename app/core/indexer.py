import httpx
import time
import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()


class IndexerClient:
    """Client for interacting with the Document Indexer API."""

    def __init__(self, base_url: str = None, api_key: str = None, timeout: Optional[float] = None):
        self.base_url = base_url or os.getenv("INDEXER_BASE_URL", "")
        self.api_key = api_key or os.getenv("INDEXER_API_KEY", "")
        self.timeout = timeout if timeout is not None else float(os.getenv("SERVER_TIMEOUT", "600"))
        self.headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        self.client = httpx.Client(timeout=self.timeout)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Perform an HTTP request with a client-level timeout and clear timeout errors."""
        try:
            response = self.client.request(method, url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise httpx.TimeoutException(f"Request to {url} timed out after {self.timeout} seconds") from exc

    def upload_document(self, file_path: str) -> Dict[str, Any]:
        """Upload a document for processing and return the task_id."""
        url = f"{self.base_url}/upload"
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')}
            response = self._request("POST", url, files=files, headers=self.headers)

        return response.json()

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get the status of a processing task."""
        url = f"{self.base_url}/status/{task_id}"
        response = self._request("GET", url, headers=self.headers)
        return response.json()

    def wait_for_completion(self, task_id: str, poll_interval: int = 2, timeout: int = 600) -> Dict[str, Any]:
        """Poll task status until completed or failed."""
        start_time = time.time()
        while True:
            try:
                status_data = self.get_task_status(task_id)
            except httpx.TimeoutException:
                if time.time() - start_time > timeout:
                    raise Exception(f"Indexing timeout after {timeout} seconds")
                time.sleep(poll_interval)
                continue

            status = status_data.get("status")

            if status == "completed":
                return status_data
            elif status == "failed":
                raise Exception(f"Indexing failed: {status_data.get('error')}")
            elif status in ["pending", "processing"]:
                if time.time() - start_time > timeout:
                    raise Exception(f"Indexing timeout after {timeout} seconds")
                time.sleep(poll_interval)
            else:
                raise Exception(f"Unknown task status: {status}")

    def get_document_chunks(self, doc_stem: str) -> Dict[str, Any]:
        """Retrieve the processed chunks and embedding metadata for a specific document."""
        url = f"{self.base_url}/chunks/{doc_stem}"
        response = self._request("GET", url, headers=self.headers)
        return response.json()

    def download_chunks_file(self, doc_stem: str, output_path: str) -> str:
        """Download the JSON file containing the processed chunks."""
        url = f"{self.base_url}/download/chunks/{doc_stem}_chunks.json"
        response = self._request("GET", url, headers=self.headers)

        with open(output_path, 'wb') as f:
            f.write(response.content)

        return output_path

    def process_document(self, file_path: str, output_chunks_path: Optional[str] = None) -> Dict[str, Any]:
        """Complete workflow: upload document, wait for completion, and get chunks."""
        # Upload document
        upload_response = self.upload_document(file_path)
        task_id = upload_response.get("task_id")

        if not task_id:
            raise Exception("No task_id returned from upload")

        # Wait for completion
        status_data = self.wait_for_completion(task_id)

        # Extract doc_stem from result
        result = status_data.get("result")
        if not result or "doc_stem" not in result:
            raise Exception("No doc_stem found in task result")

        doc_stem = result["doc_stem"]

        # Get document chunks
        chunks_data = self.get_document_chunks(doc_stem)

        if output_chunks_path:
            self.download_chunks_file(doc_stem, output_chunks_path)

        return chunks_data

    def close(self):
        """Close the HTTP client."""
        self.client.close()
