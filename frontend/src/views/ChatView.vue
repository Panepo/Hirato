<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { api } from "../api/client";
import SessionSidebar from "../components/SessionSidebar.vue";
import { useChatStream } from "../composables/useChatStream";

const props = defineProps<{ channelId: string }>();

const sidebarRef = ref<InstanceType<typeof SessionSidebar> | null>(null);
const currentSessionId = ref<string | null>(null);
const chatAreaRef = ref<HTMLElement | null>(null);
const input = ref("");

const { messages, sending, metricsText, sendMessage, reset } = useChatStream();

const showMetrics = computed(
  () =>
    !!metricsText.value &&
    messages.value.length > 0 &&
    messages.value[messages.value.length - 1].role === "assistant"
);

function scrollToBottom() {
  nextTick(() => {
    if (chatAreaRef.value)
      chatAreaRef.value.scrollTop = chatAreaRef.value.scrollHeight;
  });
}

async function selectSession(sessionId: string) {
  const session = await api.get<{
    id: string;
    messages: { role: string; content: string }[];
  }>(`/sessions/${encodeURIComponent(sessionId)}`);
  currentSessionId.value = sessionId;
  messages.value = session.messages.map((m) => ({
    role: m.role === "user" ? ("user" as const) : ("assistant" as const),
    content: m.content,
  }));
  scrollToBottom();
}

async function newChat() {
  const session = await api.post<{ id: string }>("/sessions", {
    channel_id: props.channelId,
  });
  currentSessionId.value = session.id;
  reset();
  sidebarRef.value?.refresh();
}

async function onSend() {
  const text = input.value.trim();
  if (!text || sending.value) return;
  input.value = "";
  await sendMessage(text, props.channelId, currentSessionId.value, {
    onSessionId: (id) => {
      if (id !== currentSessionId.value) {
        currentSessionId.value = id;
        sidebarRef.value?.refresh();
      }
    },
    onTitleUpdated: () => sidebarRef.value?.refresh(),
  });
  scrollToBottom();
}

watch(
  () => props.channelId,
  () => {
    currentSessionId.value = null;
    reset();
  }
);
</script>

<template>
  <div id="main-layout">
    <SessionSidebar
      ref="sidebarRef"
      :channel-id="channelId"
      :active-session-id="currentSessionId"
      @select="selectSession"
      @new-chat="newChat"
    />
    <div id="chat-panel">
      <div id="chat-area" ref="chatAreaRef">
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="bubble-row"
          :class="m.role === 'user' ? 'user' : 'secretary'"
        >
          <div class="bubble" :class="m.role === 'user' ? 'user' : 'secretary'">
            <div class="bubble-content">{{ m.content }}</div>
          </div>
        </div>
        <div v-if="showMetrics" class="metrics-bar">{{ metricsText }}</div>
      </div>
      <div id="input-bar">
        <textarea
          v-model="input"
          rows="1"
          placeholder="Type a progress report or ask a question..."
          @keydown.enter.exact.prevent="onSend"
        ></textarea>
        <button id="btn-send" :disabled="sending" @click="onSend">Send</button>
      </div>
    </div>
  </div>
</template>
