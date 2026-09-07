<script setup lang="ts">
import { ref, watch } from "vue";
import { api } from "../api/client";

defineOptions({
  name: "UserQueryModal",
});

interface Props {
  modelValue: boolean;
}

interface Emits {
  (e: "update:modelValue", value: boolean): void;
  (e: "select", userId: string, name: string): void;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: false,
});

const emit = defineEmits<Emits>();

const identifier = ref("");
const searchResults = ref<
  Array<{ empno: string; name: string; cc_mail_name: string }>
>([]);
const loading = ref(false);
const error = ref("");

watch(
  () => props.modelValue,
  (isOpen) => {
    if (isOpen) {
      identifier.value = "";
      searchResults.value = [];
      error.value = "";
      loading.value = false;
    }
  }
);

async function searchUsers() {
  if (!identifier.value.trim()) {
    error.value = "Please enter an employee number or name";
    return;
  }

  loading.value = true;
  error.value = "";

  try {
    const results = await api.get<
      Array<{ empno: string; name: string; cc_mail_name: string }>
    >(`/user/query/${encodeURIComponent(identifier.value.trim())}`);
    searchResults.value = results;
  } catch (err) {
    if (err instanceof Error) {
      error.value = err.message || "Failed to search users";
    } else {
      error.value = "Failed to search users";
    }
    searchResults.value = [];
  } finally {
    loading.value = false;
  }
}

function onSelectUser(userId: string, name: string) {
  emit("select", userId, name);
  emit("update:modelValue", false);
}
</script>

<template>
  <div
    v-if="modelValue"
    class="user-query-modal-overlay"
    @click.self="emit('update:modelValue', false)"
  >
    <div class="user-query-modal">
      <div class="modal-header">
        <h3>Query User by Identifier</h3>
        <button class="close-btn" @click="emit('update:modelValue', false)">
          &times;
        </button>
      </div>

      <div class="modal-body">
        <div class="search-section">
          <div class="input-group">
            <label for="identifier">Employee Number or Name:</label>
            <input
              id="identifier"
              v-model="identifier"
              type="text"
              placeholder="e.g., 123456 or John Doe"
              @keyup.enter="searchUsers"
            />
            <button class="search-btn" :disabled="loading" @click="searchUsers">
              {{ loading ? "Searching..." : "Search" }}
            </button>
          </div>

          <div v-if="error" class="error-message">
            {{ error }}
          </div>
        </div>

        <div v-if="searchResults.length > 0" class="results-section">
          <h4>Search Results</h4>
          <div class="results-list">
            <div
              v-for="result in searchResults"
              :key="result.empno"
              class="result-item"
              @click="onSelectUser(result.empno, result.name)"
            >
              <div class="result-primary">
                <span class="empno">{{ result.empno }}</span>
                <span class="name">{{ result.name }}</span>
              </div>
              <div class="result-secondary">
                {{ result.cc_mail_name }}
              </div>
            </div>
          </div>
        </div>

        <div
          v-if="!loading && searchResults.length === 0 && identifier"
          class="no-results"
        >
          No users found matching "{{ identifier }}"
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.user-query-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.user-query-modal {
  background: var(--bg-primary);
  border-radius: 8px;
  width: 90%;
  position: relative;
  z-index: 10000;
  max-width: 600px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--text-secondary);
  padding: 0;
  line-height: 1;
}

.close-btn:hover {
  color: var(--text-primary);
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
}

.search-section {
  margin-bottom: 20px;
}

.input-group {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.input-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.input-group input {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 1rem;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.input-group input:focus {
  outline: none;
  border-color: var(--accent-color);
}

.search-btn {
  padding: 10px 20px;
  background: var(--accent-color);
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.875rem;
  font-weight: 500;
  white-space: nowrap;
}

.search-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.search-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-message {
  margin-top: 10px;
  padding: 10px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 4px;
  color: #ef4444;
  font-size: 0.875rem;
}

.results-section h4 {
  margin: 0 0 12px 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-secondary);
}

.results-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.result-item {
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.result-item:hover {
  border-color: var(--accent-color);
  background: var(--bg-tertiary);
}

.result-primary {
  display: flex;
  gap: 12px;
  margin-bottom: 4px;
}

.empno {
  font-weight: 600;
  color: var(--accent-color);
  font-family: monospace;
}

.name {
  font-weight: 500;
  color: var(--text-primary);
}

.result-secondary {
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.no-results {
  text-align: center;
  padding: 24px;
  color: var(--text-secondary);
  font-size: 0.875rem;
}
</style>
