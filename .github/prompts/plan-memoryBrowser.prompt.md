# Plan: Memory Browser — List & Delete Individual Memory Items

## Context
ChromaDB stores individual documents (memories) per project. Currently there is no way
to view or remove individual entries — only entire projects can be deleted.
A missing `DELETE /api/projects/{id}` handler also needs to be wired up.

## Phase 1 — Backend: store.py

Add two methods to `ChromaStore` in `app/memory/store.py`:

1. `list_memories(project_id: str) -> list[dict]`
   - Call `collection.get(include=["documents", "metadatas"])` (no embeddings)
   - Return list of `{id, preview, date, type, source, section}` where
     `preview` = first 150 chars of document text
   - Sort by `date` descending (metadata["date"], fallback to empty string)

2. `delete_memory(project_id: str, memory_id: str) -> bool`
   - Call `collection.delete(ids=[memory_id])`
   - Return True on success; raise HTTPException-safe exception if project not found

## Phase 2 — Backend: routes.py

Add three routes to `app/api/routes.py`:

1. `DELETE /api/projects/{project_id}` (already called by frontend, currently missing)
   - Call `chroma_store.delete_project(project_id)`
   - Return `{"ok": true}`

2. `GET /api/projects/{project_id}/memories`
   - Call `chroma_store.list_memories(project_id)`
   - Return list of memory dicts; 404 if project not found

3. `DELETE /api/projects/{project_id}/memories/{memory_id}`
   - Call `chroma_store.delete_memory(project_id, memory_id)`
   - Return `{"ok": true}`; 404 if project/memory not found

## Phase 3 — Frontend: static/index.html

### 3a. Topbar button
Add `<button id="btn-browse-memory">🗂 Memory</button>` in topbar, after Delete Project button.
Style it with `background: #6366f1; color: #fff;` (indigo, distinct from existing buttons).
Disabled when no project selected.

### 3b. Memory browser modal CSS
Add styles (similar to existing `.modal` but wider — 680px):
- `.memory-list` — scrollable list container (max-height 420px, overflow-y auto)
- `.memory-item` — row with flex layout, border-bottom
- `.memory-type-badge` — small pill for type (raw=gray, summary=blue, reference_doc=green)
- `.memory-item-preview` — truncated content preview text
- `.memory-item-meta` — date + source/section in small muted text
- `.btn-delete-memory` — small ✕ button, shown on hover

### 3c. Memory browser modal HTML
New `<div class="modal-backdrop" id="memory-modal-backdrop">` with:
- Header: "Memory Browser" + item count `<span id="memory-count">`
- List container: `<div id="memory-list" class="memory-list">`
- Close button: `<button id="memory-modal-close">Close</button>`
- Empty state: hidden `<div id="memory-empty">No memories stored for this project.</div>`
- Loading state: `<div id="memory-loading">Loading…</div>`

### 3d. Frontend JS
- `btnBrowseMemory` wired to `projectSelect.change` listener (disabled/enabled)
- `async function openMemoryBrowser()` — fetches `GET api/projects/{id}/memories`,
  renders items into `#memory-list`, shows count, opens modal
- `function renderMemoryItem(item)` — builds DOM for one memory row with delete button
- Delete handler — calls `DELETE api/projects/{pid}/memories/{mid}`,
  removes item from DOM, decrements count display, shows toast
- Close button + backdrop-click close modal (same pattern as existing modal)
- `btnBrowseMemory.addEventListener('click', openMemoryBrowser)`
- Wire into `projectSelect` change listener to also disable `btnBrowseMemory`

## Verification
1. Select a project → "Memory" button becomes enabled
2. Click "Memory" → modal opens with list of stored items (id, type, date, preview)
3. Click ✕ on an item → confirm dialog → item disappears from list, toast confirms deletion
4. Verify ChromaDB: deleted item no longer returned in subsequent searches
5. Delete Project button now works (was broken before) — verify project removed from dropdown
6. No project selected → all three action buttons disabled

## Decisions
- Previews capped at 150 chars to keep the list scannable
- No pagination for now (return all items); revisit if collections grow beyond ~500 items
- No search/filter within the memory browser in this iteration (keep it simple)
- `DELETE /api/projects/{id}` fix is included as it's a pre-existing gap directly related
