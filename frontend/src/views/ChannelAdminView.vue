<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api/client";
import { useAuthStore } from "../stores/auth";
import { useChannelsStore } from "../stores/channels";

const props = defineProps<{ channelId: string }>();
const auth = useAuthStore();
const channelsStore = useChannelsStore();

interface RoleRow {
  channel_id: string;
  user_id: string;
  role: string;
}

const roles = ref<RoleRow[]>([]);
const isOpen = ref(true);
const newUserId = ref("");
const newRole = ref<"viewer" | "writer">("viewer");
const newManagerId = ref("");

async function load() {
  roles.value = await api.get<RoleRow[]>(
    `/channels/${encodeURIComponent(props.channelId)}/roles`
  );
  const channel = channelsStore.getChannel(props.channelId);
  if (channel) isOpen.value = channel.is_open;
}

onMounted(load);

async function toggleOpen() {
  await channelsStore.setChannelOpen(props.channelId, !isOpen.value);
  isOpen.value = !isOpen.value;
}

async function addManager() {
  if (!newManagerId.value.trim()) return;
  await api.post(`/channels/${encodeURIComponent(props.channelId)}/managers`, {
    user_id: newManagerId.value.trim(),
  });
  newManagerId.value = "";
  await load();
}

async function addRole() {
  if (!newUserId.value.trim()) return;
  const path = newRole.value === "writer" ? "writers" : "viewers";
  await api.post(`/channels/${encodeURIComponent(props.channelId)}/${path}`, {
    user_id: newUserId.value.trim(),
  });
  newUserId.value = "";
  await load();
}

async function removeRole(row: RoleRow) {
  const path =
    row.role === "manager"
      ? "managers"
      : row.role === "writer"
      ? "writers"
      : "viewers";
  await api.delete(
    `/channels/${encodeURIComponent(
      props.channelId
    )}/${path}/${encodeURIComponent(row.user_id)}`
  );
  await load();
}
</script>

<template>
  <div class="channel-admin-page">
    <h2>Channel Admin \u2014 {{ channelId }}</h2>

    <section>
      <h3>Visibility</h3>
      <label>
        <input type="checkbox" :checked="isOpen" @change="toggleOpen" />
        Open channel (visible to all users)
      </label>
    </section>

    <section v-if="auth.isSiteAdmin">
      <h3>Managers</h3>
      <div class="role-add-row">
        <input v-model="newManagerId" placeholder="User ID\u2026" />
        <button @click="addManager">Add manager</button>
      </div>
    </section>

    <section>
      <h3>Writers / Viewers</h3>
      <div class="role-add-row">
        <input v-model="newUserId" placeholder="User ID\u2026" />
        <select v-model="newRole">
          <option value="viewer">viewer</option>
          <option value="writer">writer</option>
        </select>
        <button @click="addRole">Add</button>
      </div>
    </section>

    <section>
      <h3>Current roles</h3>
      <table>
        <thead>
          <tr>
            <th>User</th>
            <th>Role</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in roles" :key="row.user_id + row.role">
            <td>{{ row.user_id }}</td>
            <td>{{ row.role }}</td>
            <td>
              <button
                v-if="row.role !== 'manager' || auth.isSiteAdmin"
                @click="removeRole(row)"
              >
                Remove
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
