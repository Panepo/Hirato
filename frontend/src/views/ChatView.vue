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

const {
  messages,
  sending,
  metricsText,
  sendMessage,
  regenerateMessage,
  reset,
} = useChatStream();

const copiedIndex = ref<number | null>(null);
let copiedTimeout: ReturnType<typeof setTimeout> | null = null;

async function copyMessage(index: number, content: string) {
  try {
    await navigator.clipboard.writeText(content);
  } catch {
    return;
  }
  copiedIndex.value = index;
  if (copiedTimeout) clearTimeout(copiedTimeout);
  copiedTimeout = setTimeout(() => {
    copiedIndex.value = null;
  }, 1500);
}

const showMetrics = computed(
  () =>
    !!metricsText.value &&
    messages.value.length > 0 &&
    messages.value[messages.value.length - 1].role === "assistant"
);

const canRegenerate = computed(
  () =>
    !sending.value &&
    !!currentSessionId.value &&
    messages.value.length > 0 &&
    messages.value[messages.value.length - 1].role === "assistant"
);

async function onRegenerate() {
  if (!canRegenerate.value || !currentSessionId.value) return;
  await regenerateMessage(props.channelId, currentSessionId.value, {
    onTitleUpdated: () => sidebarRef.value?.refresh(),
  });
  scrollToBottom();
}

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
            <div class="bubble-actions">
              <button
                v-if="
                  m.role !== 'user' &&
                  i === messages.length - 1 &&
                  canRegenerate
                "
                class="btn-regenerate"
                type="button"
                title="Regenerate response"
                aria-label="Regenerate response"
                @click="onRegenerate"
              >
                <svg
                  viewBox="0 0 24 24"
                  width="16"
                  height="16"
                  fill="currentColor"
                >
                  <path
                    d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"
                  />
                </svg>
              </button>
              <button
                class="btn-copy"
                type="button"
                :title="copiedIndex === i ? 'Copied!' : 'Copy'"
                :aria-label="copiedIndex === i ? 'Copied!' : 'Copy'"
                @click="copyMessage(i, m.content)"
              >
                <svg
                  v-if="copiedIndex === i"
                  viewBox="0 0 24 24"
                  width="16"
                  height="16"
                  fill="currentColor"
                >
                  <path d="M9 16.17L4.83 12l-1.41 1.41L9 19 21 7l-1.41-1.41z" />
                </svg>
                <svg
                  v-else
                  viewBox="0 0 24 24"
                  width="16"
                  height="16"
                  fill="currentColor"
                >
                  <path
                    d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"
                  />
                </svg>
              </button>
            </div>
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
