<script setup lang="ts">
import { computed } from "vue";

export interface MemoryItem {
  id: string;
  content: string;
  type?: string;
  source?: string;
  title?: string;
  tags?: string[] | string;
  date?: string;
  section?: string;
  preview?: string;
}

const props = defineProps<{ items: MemoryItem[]; selected: Set<string> }>();
const emit = defineEmits<{
  open: [item: MemoryItem];
  toggle: [id: string, checked: boolean];
  delete: [item: MemoryItem];
}>();

function normalizeTags(item: MemoryItem): string[] {
  const raw = item.tags;
  if (!raw) return [];
  const tags = Array.isArray(raw) ? raw : [raw];
  return tags
    .flatMap((t) => (typeof t === "string" ? t.split(",") : [t]))
    .map((t) => String(t).trim())
    .filter(Boolean)
    .slice(0, 5);
}

function displayData(item: MemoryItem) {
  const title = item.title || "Untitled memory";
  const source = item.source || item.type || "summary";
  const tags = normalizeTags(item);
  const preview = item.preview || (item.content || "").trim().slice(0, 180);
  return { title, source, tags, date: item.date || "", preview };
}

function typeClass(source: string): string {
  return ["raw", "summary", "reference_doc"].includes(source)
    ? source
    : "unknown";
}

function metaLine(item: MemoryItem): string {
  const d = displayData(item);
  return [d.date, d.source, item.section].filter(Boolean).join(" \u2022 ");
}

const channelItems = computed(() =>
  props.items.filter((i) => i.type === "raw" || i.type === "summary")
);
const refItems = computed(() =>
  props.items.filter((i) => i.type === "reference_doc")
);
const otherItems = computed(() =>
  props.items.filter(
    (i) => !["raw", "summary", "reference_doc"].includes(i.type || "")
  )
);

const refGroups = computed(() => {
  const bySource = new Map<string, MemoryItem[]>();
  for (const item of refItems.value) {
    const key =
      item.source && item.source !== "reference_doc"
        ? item.source
        : "Unknown file";
    if (!bySource.has(key)) bySource.set(key, []);
    bySource.get(key)!.push(item);
  }
  return new Map(
    [...bySource.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  );
});
</script>

<template>
  <div class="memory-list">
    <details v-if="channelItems.length" class="memory-group" open>
      <summary class="memory-group-header">
        Channel Memory
        <span class="memory-group-count">{{ channelItems.length }}</span>
      </summary>
      <div class="memory-group-items">
        <div
          v-for="item in channelItems"
          :key="item.id"
          class="memory-item"
          @click="emit('open', item)"
        >
          <input
            type="checkbox"
            class="memory-checkbox"
            :checked="selected.has(item.id)"
            @click.stop
            @change="emit('toggle', item.id, ($event.target as HTMLInputElement).checked)"
          />
          <div class="memory-item-body">
            <span
              class="memory-type-badge"
              :class="typeClass(displayData(item).source)"
              >{{ displayData(item).source }}</span
            >
            <div class="memory-item-title">{{ displayData(item).title }}</div>
            <div class="memory-item-preview">
              {{ displayData(item).preview || "(empty)" }}
            </div>
            <div class="memory-item-meta">{{ metaLine(item) }}</div>
            <div class="memory-item-tags">
              <span
                v-for="tag in displayData(item).tags"
                :key="tag"
                class="memory-tag-badge"
                >{{ tag }}</span
              >
            </div>
          </div>
          <button
            class="btn-delete-memory"
            title="Delete this memory"
            @click.stop="emit('delete', item)"
          >
            ✕
          </button>
        </div>
      </div>
    </details>

    <details v-if="refItems.length" class="memory-group" open>
      <summary class="memory-group-header">
        Reference Docs
        <span class="memory-group-count">{{ refItems.length }}</span>
      </summary>
      <div class="memory-group-items">
        <details
          v-for="[fileName, fileItems] in refGroups"
          :key="fileName"
          class="memory-subgroup"
          open
        >
          <summary class="memory-group-header memory-subgroup-header">
            {{ fileName }}
            <span class="memory-group-count">{{ fileItems.length }}</span>
          </summary>
          <div class="memory-group-items">
            <div
              v-for="item in fileItems"
              :key="item.id"
              class="memory-item"
              @click="emit('open', item)"
            >
              <input
                type="checkbox"
                class="memory-checkbox"
                :checked="selected.has(item.id)"
                @click.stop
                @change="emit('toggle', item.id, ($event.target as HTMLInputElement).checked)"
              />
              <div class="memory-item-body">
                <span
                  class="memory-type-badge"
                  :class="typeClass(displayData(item).source)"
                  >{{ displayData(item).source }}</span
                >
                <div class="memory-item-title">
                  {{ displayData(item).title }}
                </div>
                <div class="memory-item-preview">
                  {{ displayData(item).preview || "(empty)" }}
                </div>
                <div class="memory-item-meta">{{ metaLine(item) }}</div>
              </div>
              <button
                class="btn-delete-memory"
                title="Delete this memory"
                @click.stop="emit('delete', item)"
              >
                ✕
              </button>
            </div>
          </div>
        </details>
      </div>
    </details>

    <details v-if="otherItems.length" class="memory-group" open>
      <summary class="memory-group-header">
        Other <span class="memory-group-count">{{ otherItems.length }}</span>
      </summary>
      <div class="memory-group-items">
        <div
          v-for="item in otherItems"
          :key="item.id"
          class="memory-item"
          @click="emit('open', item)"
        >
          <input
            type="checkbox"
            class="memory-checkbox"
            :checked="selected.has(item.id)"
            @click.stop
            @change="emit('toggle', item.id, ($event.target as HTMLInputElement).checked)"
          />
          <div class="memory-item-body">
            <span class="memory-type-badge unknown">{{
              displayData(item).source
            }}</span>
            <div class="memory-item-title">{{ displayData(item).title }}</div>
            <div class="memory-item-preview">
              {{ displayData(item).preview || "(empty)" }}
            </div>
          </div>
          <button
            class="btn-delete-memory"
            title="Delete this memory"
            @click.stop="emit('delete', item)"
          >
            ✕
          </button>
        </div>
      </div>
    </details>
  </div>
</template>
