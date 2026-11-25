import { createClient } from '@supabase/supabase-js'
import { api } from './messagingApi'

// One content-free channel per signed-in user, shared by every listener.
const listeners = new Set()
let session = null
let connected = false

const notify = () => listeners.forEach((listener) => listener())

function onVisible() {
  if (document.visibilityState === 'visible') notify()
}

async function connect(current) {
  try {
    const config = await api('/api/realtime')
    if (session !== current || !config.enabled) return
    current.client = createClient(config.url, config.key, {
      auth: { persistSession: false, autoRefreshToken: false },
    })
    current.client
      .channel(config.topic)
      .on('broadcast', { event: 'changed' }, () => {
        if (session === current) notify()
      })
      .subscribe((status) => {
        if (session !== current) return
        const next = status === 'SUBSCRIBED'
        // Refetch after every (re)subscribe, and on loss to speed up polling.
        const changed = next || connected
        connected = next
        if (changed) notify()
      })
  } catch {
    if (session === current)
      current.retry = setTimeout(() => connect(current), 30000)
  }
}

function disconnect() {
  const current = session
  session = null
  connected = false
  document.removeEventListener('visibilitychange', onVisible)
  clearTimeout(current.retry)
  current.client?.removeAllChannels()
}

export const isConnected = () => connected

export function subscribe(listener) {
  listeners.add(listener)
  if (!session) {
    session = {}
    document.addEventListener('visibilitychange', onVisible)
    connect(session)
  }
  return () => {
    listeners.delete(listener)
    // Effects that re-run resubscribe at once; only close when nobody does.
    queueMicrotask(() => {
      if (session && !listeners.size) disconnect()
    })
  }
}
