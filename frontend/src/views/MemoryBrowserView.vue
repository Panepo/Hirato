<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api } from "../api/client";
import MemoryList from "../components/MemoryList.vue";
import type { MemoryItem } from "../components/MemoryList.vue";
import MemoryDetailPanel from "../components/MemoryDetailPanel.vue";

const props = defineProps<{ channelId: string }>();

const items = ref<MemoryItem[]>([]);
const loading = ref(true);
const error = ref("");
const selected = ref<Set<string>>(new Set());
const detailItem = ref<MemoryItem | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    items.value = await api.get<MemoryItem[]>(
      `/channels/${encodeURIComponent(props.channelId)}/memories`
    );
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load memories";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function toggleSelect(id: string, checked: boolean) {
  if (checked) selected.value.add(id);
  else selected.value.delete(id);
  selected.value = new Set(selected.value);
}

function toggleSelectAll(checked: boolean) {
  selected.value = checked ? new Set(items.value.map((i) => i.id)) : new Set();
}

async function deleteItem(item: MemoryItem) {
  if (!confirm("Delete this memory entry? This cannot be undone.")) return;
  await api.delete(
    `/channels/${encodeURIComponent(
      props.channelId
    )}/memories/${encodeURIComponent(item.id)}`
  );
  items.value = items.value.filter((i) => i.id !== item.id);
  selected.value.delete(item.id);
  if (detailItem.value?.id === item.id) detailItem.value = null;
}

async function deleteSelected() {
  if (selected.value.size === 0) return;
  if (
    !confirm(
      `Delete ${selected.value.size} selected memory entries? This cannot be undone.`
    )
  )
    return;
  await api.delete(
    `/channels/${encodeURIComponent(props.channelId)}/memories`,
    {
      memory_ids: Array.from(selected.value),
    }
  );
  items.value = items.value.filter((i) => !selected.value.has(i.id));
  selected.value = new Set();
}

async function saveEdit(content: string) {
  if (!detailItem.value) return;
  await api.put(
    `/channels/${encodeURIComponent(
      props.channelId
    )}/memories/${encodeURIComponent(detailItem.value.id)}`,
    { content }
  );
  detailItem.value.content = content;
  const found = items.value.find((i) => i.id === detailItem.value!.id);
  if (found) found.content = content;
}

function exportMemories() {
  const data = {
    channel_id: props.channelId,
    exported_at: new Date().toISOString(),
    memories: items.value,
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${props.channelId}-memories.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function triggerImport() {
  fileInput.value?.click();
}

async function onImportFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (!Array.isArray(data.memories))
      throw new Error('Invalid format: expected a "memories" array.');
    const result = await api.post<{ imported: number; skipped: number }>(
      `/channels/${encodeURIComponent(props.channelId)}/memories/import`,
      { memories: data.memories }
    );
    alert(`Imported: ${result.imported}, Skipped: ${result.skipped}`);
    await load();
  } catch (e) {
    alert(`Import failed: ${e instanceof Error ? e.message : String(e)}`);
  } finally {
    input.value = "";
  }
}

const allChecked = computed(
  () => items.value.length > 0 && selected.value.size === items.value.length
);
</script>

<template>
  <div class="memory-browser-page">
    <template v-if="!detailItem">
      <div id="memory-header">
        <h2>Memory Browser</h2>
        <span id="memory-count"
          >({{ items.length }} item{{ items.length !== 1 ? "s" : "" }})</span
        >
      </div>
      <div v-if="selected.size > 0" id="memory-selection-bar">
        <input
          type="checkbox"
          :checked="allChecked"
          @change="toggleSelectAll(($event.target as HTMLInputElement).checked)"
        />
        <label>Select All</label>
        <button @click="deleteSelected">
          Delete Selected ({{ selected.size }})
        </button>
      </div>
      <div v-if="loading" id="memory-loading">Loading\u2026</div>
      <div v-else-if="error" id="memory-empty">{{ error }}</div>
      <div v-else-if="items.length === 0" id="memory-empty">
        No memories stored for this channel.
      </div>
      <MemoryList
        v-else
        :items="items"
        :selected="selected"
        @open="detailItem = $event"
        @toggle="toggleSelect"
        @delete="deleteItem"
      />
      <div class="modal-actions">
        <button @click="triggerImport">⇧ Import</button>
        <button @click="exportMemories">⇩ Export</button>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept=".json"
        style="display: none"
        @change="onImportFile"
      />
    </template>
    <MemoryDetailPanel
      v-else
      :item="detailItem"
      @close="detailItem = null"
      @save="saveEdit"
    />
  </div>
</template>
