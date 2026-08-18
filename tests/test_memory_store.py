import json

from app.memory.store import ChromaStore


class FakeCollection:
    def __init__(self, entries=None):
        self.deleted = []
        self.entries = entries or []

    def delete(self, ids):
        self.deleted.extend(ids)

    def get(self, include=None):
        return {
            "ids": [entry["id"] for entry in self.entries],
            "documents": [entry["document"] for entry in self.entries],
            "metadatas": [entry["metadata"] for entry in self.entries],
        }


class FakeClient:
    def __init__(self, initial=None):
        self.collections = initial or {}

    def get_collection(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


def test_delete_memories_batches_and_removes_selected_ids():
    store = ChromaStore.__new__(ChromaStore)
    store._client = FakeClient()

    assert store.delete_memories("demo", ["id-1", "id-2"]) is True
    assert store._client.collections["demo"].deleted == ["id-1", "id-2"]

    assert store.delete_memory("demo", "id-3") is True
    assert store._client.collections["demo"].deleted == ["id-1", "id-2", "id-3"]


def test_list_memories_normalizes_title_source_and_tags_metadata():
    store = ChromaStore.__new__(ChromaStore)
    store._client = FakeClient({
        "demo": FakeCollection([
            {
                "id": "mem-1",
                "document": "Progress report content",
                "metadata": {
                    "date": "2026-08-18",
                    "type": "summary",
                    "source": "summary",
                    "title": "Demo update",
                    "tags": json.dumps(["demo", "testing"]),
                },
            }
        ])
    })

    memories = store.list_memories("demo")
    assert memories[0]["title"] == "Demo update"
    assert memories[0]["source"] == "summary"
    assert memories[0]["tags"] == ["demo", "testing"]
