import os
import tempfile
from pathlib import Path

import pytest

from app.core.indexer import IndexerClient


@pytest.mark.parametrize("filename", ["testimg.jpeg", "testPdf.pdf"])
def test_indexer_process_document(filename):
    """Upload a supported file to the document indexer and verify it is processed."""
    base_url = os.getenv("INDEXER_BASE_URL", "").strip()
    api_key = os.getenv("INDEXER_API_KEY", "").strip()

    if not base_url or not api_key:
        pytest.skip("Indexer environment variables not set")

    file_path = Path(__file__).with_name(filename)
    if not file_path.exists():
        pytest.skip(f"Test file not found: {file_path}")

    client = IndexerClient(base_url=base_url, api_key=api_key)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / f"{file_path.stem}_chunks.json"
        try:
            chunks_data = client.process_document(str(file_path), output_chunks_path=str(output_path))
        finally:
            client.close()

        assert isinstance(chunks_data, dict), "Indexer should return document metadata as a dictionary"
        assert chunks_data, "Indexer response should not be empty"
        assert any(
            key in chunks_data for key in ("chunks", "documents", "items", "result", "data")
        ), "Indexer response should include indexed document payload"
        assert output_path.exists(), "Chunk export file should be downloaded"
