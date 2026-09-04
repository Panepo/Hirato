<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api/client";

const props = defineProps<{ channelId: string }>();

const fileInput = ref<HTMLInputElement | null>(null);
const indexing = ref(false);
const message = ref("");

function trigger() {
  fileInput.value?.click();
}

async function onChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = input.files;
  if (!files || files.length === 0) return;

  const form = new FormData();
  for (const file of Array.from(files)) form.append("files", file);

  indexing.value = true;
  message.value = "";
  try {
    const data = await api.post<{
      imported: number;
      skipped: number;
      failed_files: { file: string; error: string }[];
    }>(
      `/channels/${encodeURIComponent(props.channelId)}/import/documents`,
      form
    );
    let msg = `Processed: ${data.imported} chunks, Skipped: ${data.skipped}`;
    if (data.failed_files?.length)
      msg += `. Failed: ${data.failed_files.length} files`;
    message.value = msg;
  } catch (e) {
    message.value = `Import failed: ${
      e instanceof Error ? e.message : String(e)
    }`;
  } finally {
    indexing.value = false;
    input.value = "";
    setTimeout(() => (message.value = ""), 4000);
  }
}
</script>

<template>
  <button @click="trigger">📄 Import Documents</button>
  <input
    ref="fileInput"
    type="file"
    multiple
    accept=".pdf,.doc,.docx,.odt,.rtf,.html,.htm,.xlsx,.xls,.csv,.pptx,.ppt,.json,.png,.jpg,.jpeg,.gif,.bmp,.tiff,.webp,.md,.txt"
    style="display: none"
    @change="onChange"
  />
  <Teleport to="body">
    <div v-if="indexing" id="indexing-overlay">
      <div id="indexing-indicator">
        <div class="spinner"></div>
        <div class="text">Indexing documents...</div>
      </div>
    </div>
    <div v-if="message && !indexing" class="import-toast">{{ message }}</div>
  </Teleport>
</template>
