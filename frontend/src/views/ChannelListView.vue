<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { useChannelsStore } from "../stores/channels";

const channelsStore = useChannelsStore();
const auth = useAuthStore();
const router = useRouter();

const showModal = ref(false);
const newName = ref("");
const creating = ref(false);
const error = ref("");

onMounted(() => channelsStore.fetchChannels());

function openChannel(channelId: string) {
  router.push({ name: "chat", params: { channelId } });
}

async function createChannel() {
  if (!newName.value.trim()) return;
  creating.value = true;
  error.value = "";
  try {
    const channel = await channelsStore.createChannel(newName.value.trim());
    showModal.value = false;
    newName.value = "";
    openChannel(channel.channel_id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to create channel";
  } finally {
    creating.value = false;
  }
}
</script>

<template>
  <div class="channel-list-page">
    <div class="channel-list-header">
      <h2>Channels</h2>
      <button v-if="auth.isSiteAdmin || auth.isSiteManager" @click="showModal = true">
        + New Channel
      </button>
    </div>

    <div
      v-if="channelsStore.loaded && channelsStore.channels.length === 0"
      class="empty"
    >
      No channels available.
    </div>

    <div class="channel-grid">
      <div
        v-for="c in channelsStore.channels"
        :key="c.channel_id"
        class="channel-card"
        @click="openChannel(c.channel_id)"
      >
        <div class="channel-card-name">{{ c.channel_id }}</div>
        <div class="channel-card-meta">
          <span class="badge" :class="c.is_open ? 'open' : 'closed'">{{
            c.is_open ? "Open" : "Closed"
          }}</span>
          <span v-if="c.role" class="badge role">{{ c.role }}</span>
        </div>
      </div>
    </div>

    <div
      v-if="showModal"
      class="modal-backdrop"
      @click.self="showModal = false"
    >
      <div class="modal">
        <h2>New Channel</h2>
        <input
          v-model="newName"
          placeholder="Channel name"
          @keydown.enter="createChannel"
        />
        <p v-if="error" class="error">{{ error }}</p>
        <div class="modal-actions">
          <button @click="showModal = false">Cancel</button>
          <button :disabled="creating" @click="createChannel">Create</button>
        </div>
      </div>
    </div>
  </div>
</template>
