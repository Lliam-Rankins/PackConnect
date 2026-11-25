import { createClient } from '@supabase/supabase-js'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { response } from './test/fixtures'

vi.unmock('./realtime')
vi.mock('@supabase/supabase-js', () => ({ createClient: vi.fn() }))
const { isConnected, subscribe } = await import('./realtime')

describe('realtime signals', () => {
  let onSignal
  let onStatus
  let client

  beforeEach(() => {
    const channel = {
      on: vi.fn((type, filter, callback) => {
        onSignal = callback
        return channel
      }),
      subscribe: vi.fn((callback) => {
        onStatus = callback
        return channel
      }),
    }
    client = { channel: vi.fn(() => channel), removeAllChannels: vi.fn() }
    vi.mocked(createClient).mockReset().mockReturnValue(client)
  })

  it('shares one channel, relays signals, and closes after the last listener', async () => {
    fetch.mockResolvedValue(
      response({ enabled: true, url: 'u', key: 'k', topic: 'user:abc' }),
    )
    const first = vi.fn()
    const second = vi.fn()
    const stopFirst = subscribe(first)
    const stopSecond = subscribe(second)
    await vi.waitFor(() => expect(client.channel).toHaveBeenCalled())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(client.channel).toHaveBeenCalledWith('user:abc')

    onStatus('SUBSCRIBED')
    expect(isConnected()).toBe(true)
    onSignal()
    onStatus('CHANNEL_ERROR')
    expect(isConnected()).toBe(false)
    expect(first).toHaveBeenCalledTimes(3)
    expect(second).toHaveBeenCalledTimes(3)

    stopFirst()
    await Promise.resolve()
    expect(client.removeAllChannels).not.toHaveBeenCalled()
    stopSecond()
    await Promise.resolve()
    expect(client.removeAllChannels).toHaveBeenCalled()
  })

  it('stays on polling when the server has realtime disabled', async () => {
    fetch.mockResolvedValue(response({ enabled: false }))
    const stop = subscribe(vi.fn())
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(createClient).not.toHaveBeenCalled()
    expect(isConnected()).toBe(false)
    stop()
  })
})
