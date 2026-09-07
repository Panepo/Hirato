<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api/client";
import { useAuthStore } from "../stores/auth";
import { useChannelsStore } from "../stores/channels";
import UserQueryModal from "../components/UserQueryModal.vue";

const props = defineProps<{ channelId: string }>();
const auth = useAuthStore();
const channelsStore = useChannelsStore();

interface RoleRow {
  channel_id: string;
  user_id: string;
  role: string;
  name: string;
}

const roles = ref<RoleRow[]>([]);
const isOpen = ref(true);
const showUserQueryModal = ref(false);
const queryTarget = ref<"manager" | "writer" | "viewer">("viewer");

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

function openUserQueryModal(target: "manager" | "writer" | "viewer") {
  queryTarget.value = target;
  showUserQueryModal.value = true;
}

async function onUserSelected(userId: string, name: string) {
  const path =
    queryTarget.value === "manager"
      ? "managers"
      : queryTarget.value === "writer"
      ? "writers"
      : "viewers";
  await api.post(`/channels/${encodeURIComponent(props.channelId)}/${path}`, {
    user_id: userId,
    name,
  });
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
    <h2>Channel Management</h2>

    <section>
      <h3>Visibility</h3>
      <label>
        <input type="checkbox" :checked="isOpen" @change="toggleOpen" />
        Open channel (visible to all users)
      </label>
    </section>

    <section v-if="auth.isSiteAdmin">
      <h3>Add Member</h3>
      <div class="role-add-row">
        <button class="query-btn" @click="openUserQueryModal('manager')">
          Add Manager
        </button>
        <button class="query-btn" @click="openUserQueryModal('writer')">
          Add Writer
        </button>
        <button class="query-btn" @click="openUserQueryModal('viewer')">
          Add Viewer
        </button>
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
            <td>{{ row.name || row.user_id }}</td>
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

    <UserQueryModal v-model="showUserQueryModal" @select="onUserSelected" />
  </div>
</template>

<style scoped>
section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

section h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}

.role-add-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.role-add-row input {
  flex: 1;
  min-width: 200px;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.role-add-row select {
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.query-btn {
  padding: 8px 16px;
  background: var(--secondary-bg);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.875rem;
  transition: all 0.2s ease;
}

.query-btn:hover {
  background: var(--accent-color);
  color: white;
  border-color: var(--accent-color);
}

button {
  padding: 8px 16px;
  background: var(--accent-color);
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.875rem;
  font-weight: 500;
  transition: opacity 0.2s ease;
}

button:hover {
  opacity: 0.9;
}

table {
  width: 100%;
  border-collapse: collapse;
}

table th,
table td {
  padding: 10px;
  text-align: left;
  border-bottom: 1px solid var(--border-color);
}

table th {
  font-weight: 600;
  color: var(--text-secondary);
}

label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
}
</style>
