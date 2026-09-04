<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import TopBar from "./components/TopBar.vue";

const route = useRoute();
const showTopBar = computed(() => route.name !== "login");
</script>

<template>
  <TopBar v-if="showTopBar" />
  <RouterView />
</template>
