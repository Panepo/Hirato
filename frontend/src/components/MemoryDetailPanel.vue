<script setup lang="ts">
import { ref, watch } from "vue";
import type { MemoryItem } from "./MemoryList.vue";

const props = defineProps<{ item: MemoryItem }>();
const emit = defineEmits<{ close: []; save: [content: string] }>();

const editing = ref(false);
const draft = ref("");

watch(
  () => props.item,
  () => {
    editing.value = false;
  }
);

function tagList(): string[] {
  const raw = props.item.tags;
  if (!raw) return [];
  return Array.isArray(raw) ? raw : [raw];
}

function metaLine(): string {
  return [props.item.date, props.item.source, props.item.section]
    .filter(Boolean)
    .join(" \u2022 ");
}

function startEdit() {
  draft.value = props.item.content || "";
  editing.value = true;
}

function cancelEdit() {
  editing.value = false;
}

function save() {
  const content = draft.value.trim();
  if (!content) return;
  emit("save", content);
  editing.value = false;
}
</script>

<template>
  <div id="memory-detail-view">
    <div id="memory-detail-header">
      <button id="memory-detail-back" @click="emit('close')">← Back</button>
      <span
        class="memory-type-badge"
        :class="
          ['raw', 'summary', 'reference_doc'].includes(item.type || '')
            ? item.type
            : 'unknown'
        "
      >
        {{ item.source || item.type || "unknown" }}
      </span>
      <span id="memory-detail-id">{{ item.id }}</span>
    </div>
    <div class="memory-detail-title">{{ item.title || "Untitled memory" }}</div>
    <div class="memory-detail-tags">
      <span v-for="tag in tagList()" :key="tag" class="memory-tag-badge">{{
        tag
      }}</span>
    </div>
    <div class="memory-item-meta">{{ metaLine() }}</div>
    <div v-if="!editing" class="memory-detail-content">
      {{ item.content || "(empty)" }}
    </div>
    <textarea
      v-else
      v-model="draft"
      class="memory-detail-edit-area"
      rows="10"
    ></textarea>
    <div class="modal-actions">
      <button @click="emit('close')">Close</button>
      <button v-if="!editing" @click="startEdit">✎ Edit</button>
      <template v-else>
        <button @click="save">Save</button>
        <button @click="cancelEdit">Cancel</button>
      </template>
    </div>
  </div>
</template>
