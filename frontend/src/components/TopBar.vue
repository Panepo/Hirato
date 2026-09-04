<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { useChannelsStore, canManage, canWrite } from "../stores/channels";
import ImportDocumentsPanel from "./ImportDocumentsPanel.vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const channelsStore = useChannelsStore();

const channelId = computed(() => route.params.channelId as string | undefined);
const channel = computed(() =>
  channelId.value ? channelsStore.getChannel(channelId.value) : undefined
);

function logout() {
  auth.logout();
  router.push({ name: "login" });
}
</script>

<template>
  <div id="topbar">
    <h1>Hirato LLM Secretary</h1>
    <RouterLink class="topbar-link" to="/">Channels</RouterLink>
    <template v-if="channelId">
      <RouterLink
        class="topbar-link"
        :to="{ name: 'chat', params: { channelId } }"
        >Chat</RouterLink
      >
      <RouterLink
        v-if="canWrite(channel)"
        class="topbar-link"
        :to="{ name: 'memories', params: { channelId } }"
      >
        Memory
      </RouterLink>
      <RouterLink
        v-if="canManage(channel)"
        class="topbar-link"
        :to="{ name: 'channel-admin', params: { channelId } }"
      >
        Admin
      </RouterLink>
    </template>
    <span class="spacer"></span>
    <ImportDocumentsPanel
      v-if="channelId && canWrite(channel)"
      :channel-id="channelId"
    />
    <span class="topbar-user">{{ auth.user?.name }}</span>
    <button @click="logout">Logout</button>
  </div>
</template>
