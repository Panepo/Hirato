<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api/client";

const props = defineProps<{
  channelId: string;
  activeSessionId?: string | null;
}>();
const emit = defineEmits<{ select: [sessionId: string]; "new-chat": [] }>();

interface SessionSummary {
  id: string;
  channel_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

const sessions = ref<SessionSummary[]>([]);

function relativeDate(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

async function refresh() {
  if (!props.channelId) {
    sessions.value = [];
    return;
  }
  sessions.value = await api.get<SessionSummary[]>(
    `/sessions?channel_id=${encodeURIComponent(props.channelId)}`
  );
}

async function remove(sessionId: string, event: Event) {
  event.stopPropagation();
  if (!confirm("Delete this conversation?")) return;
  await api.delete(`/sessions/${encodeURIComponent(sessionId)}`);
  sessions.value = sessions.value.filter((s) => s.id !== sessionId);
}

refresh();

defineExpose({ refresh });
</script>

<template>
  <div id="sidebar">
    <button id="btn-new-chat" @click="emit('new-chat')">+ New Chat</button>
    <div id="session-list">
      <div
        v-for="s in sessions"
        :key="s.id"
        class="session-entry"
        :class="{ active: s.id === activeSessionId }"
        @click="emit('select', s.id)"
      >
        <div class="session-meta">
          <div class="session-title">{{ s.title || "New conversation" }}</div>
          <div class="session-date">{{ relativeDate(s.updated_at) }}</div>
        </div>
        <button
          class="btn-delete-session"
          title="Delete conversation"
          @click="remove(s.id, $event)"
        >
          ✕
        </button>
      </div>
    </div>
  </div>
</template>
