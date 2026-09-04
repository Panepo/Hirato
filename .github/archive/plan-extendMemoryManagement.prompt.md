## Plan: Extend Memory Management

**TL;DR** - Add title and tags generation to the extractor node, extend ChromaDB metadata to store them, update the memory browser UI to display title/date/tags/source, add tag-based retrieval to the retriever node, and add selection/bulk deletion features.

**Steps**

### Phase 1: Extend Extractor Node for Title and Tags Generation
1. Update `EXTRACTOR_PROMPT` in `app/agent/prompts.py` to include `title` (concise 4-7 word title) and `tags` (array of 3-5 relevant tags/keywords) in the JSON output
2. Update `extractor_node` in `app/agent/nodes.py` to parse and pass through the new `title` and `tags` fields from the extracted summary

### Phase 2: Extend Database Metadata Columns
1. Update `store_node` in `app/agent/nodes.py` to pass `title` and `tags` to `chroma_store.add_memory()` as metadata
2. Update `ChromaStore.list_memories()` in `app/memory/store.py` to include `title` and `tags` in the returned preview dicts
3. Update `ChromaStore.import_memories()` in `app/memory/store.py` to handle `title` and `tags` fields when importing from export format

### Phase 2.5: Extend Retriever to Use Tags for Data Retrieval
1. Update `retriever_node` in `app/agent/nodes.py` to incorporate tags into the search query or use metadata filtering to retrieve relevant documents based on tags
2. Update `ChromaStore.search_memory()` in `app/memory/store.py` to support tag-based filtering or tag-augmented query generation (e.g., appending tags to the query text or using ChromaDB's metadata filtering capabilities)

### Phase 4: Add Selection and Select All Features
1. Add a checkbox column to each memory item in the memory list
2. Add a "Select All" checkbox in the memory list header
3. Add state tracking for selected memory IDs in the JavaScript
4. Update `renderMemoryItem()` to include a checkbox that toggles selection state
5. Add event handlers for individual checkbox changes and "select all" toggle

### Phase 4: Update Memory Browser UI - Display Fields
1. Update `renderMemoryItem()` in `static/index.html` to display:
   - Source badge (summary/reference_doc/raw)
   - Title (if available, otherwise show preview)
   - Date
   - Tags (as small badge chips)
2. Update `openMemoryDetail()` in `static/index.html` to show title and tags in the detail view header

### Phase 5: Add Selection and Select All Features
1. Add a checkbox column to each memory item in the memory list
2. Add a "Select All" checkbox in the memory list header
3. Add state tracking for selected memory IDs in the JavaScript
4. Update `renderMemoryItem()` to include a checkbox that toggles selection state
5. Add event handlers for individual checkbox changes and "select all" toggle

### Phase 6: Add Bulk Deletion Button
1. Add a "Delete Selected" button in the memory browser modal actions (visible only when memories are selected)
2. Implement `deleteSelectedMemories()` function in `static/index.html` that:
   - Collects all selected memory IDs
   - Calls the existing `api/channels/{channel_id}/memories` DELETE endpoint with the `BulkDeleteMemoriesRequest` payload
   - Removes deleted items from the UI
   - Clears selection state
   - Shows toast notification with deletion count

**Relevant files**
- `app/agent/prompts.py` - EXTRACTOR_PROMPT definition
- `app/agent/nodes.py` - extractor_node, store_node, retriever_node functions
- `app/memory/store.py` - ChromaStore.list_memories(), ChromaStore.import_memories(), ChromaStore.search_memory()
- `static/index.html` - Memory browser UI, renderMemoryItem(), openMemoryDetail(), modal actions

**Verification**
1. Test extractor node generates title and tags in JSON format
2. Verify ChromaDB metadata includes `title` and `tags` fields for new memories
3. Verify retriever node incorporates tags into search queries or uses metadata filtering
4. Verify memory browser displays source badge, title, date, and tags correctly
5. Test individual memory selection via checkboxes
6. Test "Select All" functionality
7. Test bulk deletion via "Delete Selected" button
8. Verify deleted memories are removed from ChromaDB and UI

**Decisions**
- Title generation: Use the same LLM that generates the summary to also generate a concise 4-7 word title and 3-5 tags
- Metadata storage: Store `title` and `tags` in ChromaDB metadata (not as separate columns, since ChromaDB uses flexible metadata dictionaries)
- Selection UI: Use checkboxes aligned to the left of each memory item, with a "Select All" checkbox in the group header
- Bulk delete: Reuse the existing `/api/channels/{channel_id}/memories` DELETE endpoint with `BulkDeleteMemoriesRequest` payload

**Further Considerations**
1. Should tags be clickable to filter memories by tag in the UI?
Ans: Yes
2. Should the retriever use tag-based filtering or tag-augmented query generation for retrieval? (Recommend: tag-augmented query generation by appending tags to the search query)
Ans: Tag-augmented query generation
3. Should the "Select All" be per-group or across all memories in the channel? (Recommend: across all memories for simplicity)
Ans: Across all memories
4. Should deleted memories be recoverable? (Currently no, ChromaDB deletion is permanent - consistent with existing delete behavior)
Ans: No
