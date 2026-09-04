import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '../api/client'

export interface Channel {
  channel_id: string
  is_open: boolean
  role: 'viewer' | 'writer' | 'manager' | 'admin' | null
}

const WRITE_ROLES = new Set(['writer', 'manager', 'admin'])
const MANAGE_ROLES = new Set(['manager', 'admin'])

export function canWrite(channel: Channel | null | undefined): boolean {
  return !!channel && (channel.role !== null && WRITE_ROLES.has(channel.role))
}

export function canManage(channel: Channel | null | undefined): boolean {
  return !!channel && (channel.role !== null && MANAGE_ROLES.has(channel.role))
}

export const useChannelsStore = defineStore('channels', () => {
  const channels = ref<Channel[]>([])
  const loaded = ref(false)

  const byId = computed(() => new Map(channels.value.map((c) => [c.channel_id, c])))

  async function fetchChannels(): Promise<void> {
    channels.value = await api.get<Channel[]>('/channels')
    loaded.value = true
  }

  function getChannel(channelId: string): Channel | undefined {
    return byId.value.get(channelId)
  }

  async function createChannel(name: string): Promise<Channel> {
    const result = await api.post<{ channel_id: string; description: string }>('/channels', { name })
    await fetchChannels()
    return getChannel(result.channel_id)!
  }

  async function deleteChannel(channelId: string): Promise<void> {
    await api.delete(`/channels/${encodeURIComponent(channelId)}`)
    await fetchChannels()
  }

  async function setChannelOpen(channelId: string, isOpen: boolean): Promise<void> {
    await api.put(`/channels/${encodeURIComponent(channelId)}`, { is_open: isOpen })
    await fetchChannels()
  }

  return { channels, loaded, fetchChannels, getChannel, createChannel, deleteChannel, setChannelOpen }
})
