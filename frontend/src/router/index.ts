import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'
import { canManage, canWrite, useChannelsStore } from '../stores/channels'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    { path: '/channels/', name: 'channels', component: () => import('../views/ChannelListView.vue') },
    {
      path: '/channels/:channelId/chat',
      name: 'chat',
      component: () => import('../views/ChatView.vue'),
      props: true,
    },
    {
      path: '/channels/:channelId/memories',
      name: 'memories',
      component: () => import('../views/MemoryBrowserView.vue'),
      props: true,
      meta: { requiresWrite: true },
    },
    {
      path: '/channels/:channelId/admin',
      name: 'channel-admin',
      component: () => import('../views/ChannelAdminView.vue'),
      props: true,
      meta: { requiresManage: true },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.name !== 'login' && !auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isAuthenticated) {
    return { name: 'channels' }
  }

  if (auth.isAuthenticated && !auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      auth.logout()
      return { name: 'login' }
    }
  }

  const channelId = to.params.channelId as string | undefined
  if (channelId && (to.meta.requiresWrite || to.meta.requiresManage)) {
    const channels = useChannelsStore()
    if (!channels.loaded) await channels.fetchChannels()
    const channel = channels.getChannel(channelId)
    if (to.meta.requiresManage && !canManage(channel)) return { name: 'chat', params: { channelId } }
    if (to.meta.requiresWrite && !canWrite(channel)) return { name: 'chat', params: { channelId } }
  }

  return true
})

export default router
