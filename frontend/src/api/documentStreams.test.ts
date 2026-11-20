import { afterEach, describe, expect, it, vi } from 'vitest'
import { FakeEventStream, stubApi } from '../test/fakeApi.ts'
import {
  extractionStreamPath,
  isFinalEvent,
  isStreamBreak,
  parseExtractionEvent,
  parseValidationEvent,
  readExtractionRun,
  readExtractionStream,
  readValidationRun,
  readValidationStream,
  readWithReconnect,
  RECONNECT_DELAYS_MS,
  validationStreamPath,
  type ExtractionEvent,
  type ValidationEvent,
} from './documentStreams.ts'
import { ApiError, setAccessTokenProvider } from './httpClient.ts'

const POSITION = { name: 'Umsatzerlöse', value: 184300, period: '2025', source: 'GuV', page: 3 }

describe('parseValidationEvent', () => {
  it('reads the contract fields and treats null as absent', () => {
    expect(parseValidationEvent('{"overallProgress":25,"document":"d1","documentProgress":50,"error":null}')).toEqual({
      overallProgress: 25,
      document: 'd1',
      documentProgress: 50,
    })
    expect(parseValidationEvent('{"overallProgress":100,"document":"d1","error":"Mock: kein Finanzbericht erkannt."}')).toEqual({
      overallProgress: 100,
      document: 'd1',
      error: 'Mock: kein Finanzbericht erkannt.',
    })
  })

  it.each([
    ['not JSON', 'data'],
    ['no overallProgress', '{"document":"d1"}'],
    ['no document', '{"overallProgress":1}'],
    ['a wrong type', '{"overallProgress":1,"document":"d1","documentProgress":"50"}'],
    ['an array', '[]'],
  ])('rejects %s', (_case, data) => {
    expect(parseValidationEvent(data)).toBeNull()
  })
})

describe('parseExtractionEvent', () => {
  it('reads pages, counters and the position, leaving out null fields', () => {
    const data = JSON.stringify({ overallProgress: 40, document: 'd1', pages: 9, pagesRead: 3, positions: 6, position: POSITION, error: null })

    expect(parseExtractionEvent(data)).toEqual({ overallProgress: 40, document: 'd1', pages: 9, pagesRead: 3, positions: 6, position: POSITION })
  })

  it('rejects an incomplete position', () => {
    const data = JSON.stringify({ overallProgress: 40, document: 'd1', position: { name: 'Umsatz', page: 3 } })

    expect(parseExtractionEvent(data)).toBeNull()
  })
})

describe('document streams', () => {
  it('AC-7: reads the validation stream of the project and skips events off the contract', async () => {
    const api = stubApi()
    const stream = new FakeEventStream()
    api.on('GET', '/project/p1/document-validation/sse', () => stream)
    const events: ValidationEvent[] = []

    const reading = readValidationStream('p1', (event) => events.push(event))
    stream.push({ overallProgress: 50, document: 'd1', documentProgress: 100 })
    stream.push('event: other\ndata: {"overallProgress":60,"document":"d1"}\n\n')
    stream.push('data: broken\n\n')
    stream.push({ overallProgress: 100, document: '' })
    stream.end()
    await reading

    expect(events).toEqual([
      { overallProgress: 50, document: 'd1', documentProgress: 100 },
      { overallProgress: 100, document: '' },
    ])
  })

  it('reads the extraction stream of the project', async () => {
    const api = stubApi()
    const stream = new FakeEventStream()
    api.on('GET', '/project/p1/document-extraction/sse', () => stream)
    const events: ExtractionEvent[] = []

    const reading = readExtractionStream('p1', (event) => events.push(event))
    stream.push({ overallProgress: 100, document: 'd1', pagesRead: 3, pages: 3 })
    stream.end()
    await reading

    expect(events).toEqual([{ overallProgress: 100, document: 'd1', pagesRead: 3, pages: 3 }])
  })

  it('builds the stream paths of the contract', () => {
    expect(validationStreamPath('p 1')).toBe('/project/p%201/document-validation/sse')
    expect(extractionStreamPath('p1')).toBe('/project/p1/document-extraction/sse')
  })
})

describe('reconnecting a broken stream', () => {
  const VALIDATION = validationStreamPath('p1')
  type Reply = () => Response | FakeEventStream

  afterEach(() => {
    setAccessTokenProvider(null)
    vi.useRealTimers()
  })

  /** Answers the requests to `path` in order with `replies`; the returned list holds the streams handed out. */
  function backend(path: string, ...replies: Reply[]) {
    const api = stubApi()
    const streams: FakeEventStream[] = []
    let next = 0
    api.on('GET', path, () => {
      const reply = (replies[next] ?? replies[replies.length - 1] ?? (() => new FakeEventStream()))()
      next += 1
      if (reply instanceof FakeEventStream) {
        streams.push(reply)
      }
      return reply
    })
    return { api, streams, requests: () => api.sent('GET', path) }
  }

  const stream: Reply = () => new FakeEventStream()
  const status = (code: number): Reply => () => new Response(null, { status: code })

  /** How `reading` settles, without leaving a rejection unhandled while the test goes on. */
  function outcome(reading: Promise<void>): Promise<unknown> {
    return reading.then(
      () => 'resolved',
      (error: unknown) => error,
    )
  }

  /** A sleep that returns at once and records each wait. */
  function recordingSleep() {
    const waits: number[] = []
    const sleep = async (ms: number, signal?: AbortSignal) => {
      waits.push(ms)
      signal?.throwIfAborted()
    }
    return { waits, sleep }
  }

  it('knows the final event of a run: overallProgress 100 or an error of the whole run', () => {
    expect(isFinalEvent({ overallProgress: 100, document: '' })).toBe(true)
    expect(isFinalEvent({ overallProgress: 100, document: 'd1', documentProgress: 100 })).toBe(true)
    expect(isFinalEvent({ overallProgress: 40, document: '', error: 'Analyse nicht verfügbar' })).toBe(true)
    expect(isFinalEvent({ overallProgress: 99, document: 'd1', error: 'Mock: kein Finanzbericht erkannt.' })).toBe(false)
    expect(isFinalEvent({ overallProgress: 99, document: '' })).toBe(false)
  })

  it('reconnects after a network error or a 5xx, never after a 4xx or another error', () => {
    expect(isStreamBreak(new TypeError('network error'))).toBe(true)
    expect(isStreamBreak(new ApiError('GET /x', 503))).toBe(true)
    expect(isStreamBreak(new ApiError('GET /x', 500))).toBe(true)
    expect(isStreamBreak(new ApiError('GET /x', 401))).toBe(false)
    expect(isStreamBreak(new ApiError('GET /x', 404))).toBe(false)
    expect(isStreamBreak(new DOMException('aborted', 'AbortError'))).toBe(false)
    expect(isStreamBreak(new Error('GET /x returned no body'))).toBe(false)
  })

  it('reconnects after a stream that closes before its final event, with a fresh token each time', async () => {
    const { streams, requests } = backend(VALIDATION, stream)
    let tokens = 0
    setAccessTokenProvider(async () => `token-${(tokens += 1)}`)
    const { waits, sleep } = recordingSleep()
    const reconnects: number[] = []
    const events: ValidationEvent[] = []

    const reading = readValidationRun('p1', (event) => events.push(event), { sleep, onReconnect: (attempt) => reconnects.push(attempt) })
    await vi.waitFor(() => expect(streams).toHaveLength(1))
    streams[0]?.push({ overallProgress: 50, document: 'd1', documentProgress: 100 })
    streams[0]?.end()
    await vi.waitFor(() => expect(streams).toHaveLength(2))
    streams[1]?.push({ overallProgress: 100, document: 'd1', documentProgress: 100 })
    streams[1]?.end()
    await reading

    expect(waits).toEqual([1000])
    expect(reconnects).toEqual([1])
    expect(events).toEqual([
      { overallProgress: 50, document: 'd1', documentProgress: 100 },
      { overallProgress: 100, document: 'd1', documentProgress: 100 },
    ])
    expect(requests().map((request) => request.headers.get('Authorization'))).toEqual(['Bearer token-1', 'Bearer token-2'])
  })

  it('reconnects after a 503 and after a broken connection', async () => {
    const { streams, requests } = backend(VALIDATION, status(503), stream, stream)
    const { waits, sleep } = recordingSleep()

    const reading = readValidationRun('p1', () => {}, { sleep })
    await vi.waitFor(() => expect(streams).toHaveLength(1))
    streams[0]?.fail(new TypeError('network error'))
    await vi.waitFor(() => expect(streams).toHaveLength(2))
    streams[1]?.push({ overallProgress: 100, document: '' })
    streams[1]?.end()
    await reading

    expect(requests()).toHaveLength(3)
    expect(waits).toEqual([1000, 3000])
  })

  it('reconnects when the access token cannot be had for a network failure, as the token provider reports it', async () => {
    const { streams, requests } = backend(VALIDATION, stream)
    let calls = 0
    setAccessTokenProvider(async () => {
      calls += 1
      if (calls === 1) {
        throw new TypeError('The access token request failed: post_request_failed')
      }
      return `token-${calls}`
    })
    const { waits, sleep } = recordingSleep()

    const reading = readValidationRun('p1', () => {}, { sleep })
    await vi.waitFor(() => expect(streams).toHaveLength(1))
    streams[0]?.push({ overallProgress: 100, document: '' })
    streams[0]?.end()
    await reading

    expect(waits).toEqual([1000])
    expect(requests().map((request) => request.headers.get('Authorization'))).toEqual(['Bearer token-2'])
  })

  it.each([401, 404])('does not reconnect after a %i', async (code) => {
    const { requests } = backend(VALIDATION, status(code), stream)
    const { waits, sleep } = recordingSleep()

    await expect(readValidationRun('p1', () => {}, { sleep })).rejects.toMatchObject({ name: 'ApiError', status: code })

    expect(requests()).toHaveLength(1)
    expect(waits).toEqual([])
  })

  it('takes an error of the whole run as final, also when the stream closes or breaks afterwards', async () => {
    const { streams, requests } = backend(VALIDATION, stream)
    const { waits, sleep } = recordingSleep()
    const events: ValidationEvent[] = []

    const closed = readValidationRun('p1', (event) => events.push(event), { sleep })
    await vi.waitFor(() => expect(streams).toHaveLength(1))
    streams[0]?.push({ overallProgress: 30, document: '', error: 'Analyse nicht verfügbar' })
    streams[0]?.end()
    await closed

    const broken = readValidationRun('p1', (event) => events.push(event), { sleep })
    await vi.waitFor(() => expect(streams).toHaveLength(2))
    streams[1]?.push({ overallProgress: 100, document: '', error: 'Analyse nicht verfügbar' })
    await vi.waitFor(() => expect(events).toHaveLength(2))
    streams[1]?.fail()
    await broken

    expect(events).toEqual([
      { overallProgress: 30, document: '', error: 'Analyse nicht verfügbar' },
      { overallProgress: 100, document: '', error: 'Analyse nicht verfügbar' },
    ])
    expect(requests()).toHaveLength(2)
    expect(waits).toEqual([])
  })

  it('gives up after 3 reconnects: resolves when the last stream closed early, rejects when it failed', async () => {
    const closing = backend(VALIDATION, stream)
    const closingSleep = recordingSleep()
    const closed = readValidationRun('p1', () => {}, { sleep: closingSleep.sleep })
    for (let index = 0; index < 4; index++) {
      await vi.waitFor(() => expect(closing.streams).toHaveLength(index + 1))
      closing.streams[index]?.push({ overallProgress: 99, document: 'd1', documentProgress: 100 })
      closing.streams[index]?.end()
    }
    await closed
    expect(closing.requests()).toHaveLength(4)
    expect(closingSleep.waits).toEqual(RECONNECT_DELAYS_MS)
    expect(RECONNECT_DELAYS_MS).toEqual([1000, 3000, 10_000])

    const failing = backend(VALIDATION, status(503))
    const failingSleep = recordingSleep()
    await expect(readValidationRun('p1', () => {}, { sleep: failingSleep.sleep })).rejects.toMatchObject({ status: 503 })
    expect(failing.requests()).toHaveLength(4)
    expect(failingSleep.waits).toEqual([1000, 3000, 10_000])
  })

  it('waits 1 s, 3 s and 10 s by default', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const { requests } = backend(VALIDATION, status(503))

    const settled = outcome(readValidationRun('p1', () => {}))
    await vi.advanceTimersByTimeAsync(999)
    expect(requests()).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(requests()).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(2999)
    expect(requests()).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(requests()).toHaveLength(3)
    await vi.advanceTimersByTimeAsync(9999)
    expect(requests()).toHaveLength(3)
    await vi.advanceTimersByTimeAsync(1)
    expect(await settled).toMatchObject({ name: 'ApiError', status: 503 })
    expect(requests()).toHaveLength(4)
  })

  it('stops waiting and connects no more once the signal aborts', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const { requests } = backend(VALIDATION, status(503))
    const controller = new AbortController()
    const reconnects: number[] = []

    const settled = outcome(readValidationRun('p1', () => {}, { signal: controller.signal, onReconnect: (attempt) => reconnects.push(attempt) }))
    await vi.advanceTimersByTimeAsync(500)
    controller.abort('left the page')
    expect(await settled).toBe('left the page')
    await vi.advanceTimersByTimeAsync(20_000)

    expect(requests()).toHaveLength(1)
    expect(reconnects).toEqual([])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not reconnect when onEvent throws', async () => {
    const { streams, requests } = backend(VALIDATION, stream)
    const { waits, sleep } = recordingSleep()
    const failure = new TypeError('bug in the handler')

    const reading = readValidationRun('p1', () => {
      throw failure
    }, { sleep })
    await vi.waitFor(() => expect(streams).toHaveLength(1))
    streams[0]?.push({ overallProgress: 10, document: 'd1' })

    await expect(reading).rejects.toBe(failure)
    expect(requests()).toHaveLength(1)
    expect(waits).toEqual([])
  })

  it('reconnects the extraction stream the same way and says so before each reconnect', async () => {
    const { streams } = backend(extractionStreamPath('p1'), stream)
    const { sleep } = recordingSleep()
    const log: string[] = []

    const reading = readExtractionRun('p1', (event) => log.push(`event ${event.pagesRead ?? ''}`), { sleep, onReconnect: (attempt) => log.push(`reconnect ${attempt}`) })
    await vi.waitFor(() => expect(streams).toHaveLength(1))
    streams[0]?.push({ overallProgress: 40, document: 'd1', pages: 3, pagesRead: 1 })
    await vi.waitFor(() => expect(log).toEqual(['event 1']))
    streams[0]?.fail()
    await vi.waitFor(() => expect(streams).toHaveLength(2))
    streams[1]?.push({ overallProgress: 100, document: 'd1', pages: 3, pagesRead: 3 })
    streams[1]?.end()
    await reading

    expect(log).toEqual(['event 1', 'reconnect 1', 'event 3'])
  })

  it('takes any connection and its own delays', async () => {
    const connections: number[] = []
    const { waits, sleep } = recordingSleep()

    await readWithReconnect<ValidationEvent>(
      async (onEvent) => {
        connections.push(connections.length + 1)
        if (connections.length === 2) {
          onEvent({ overallProgress: 100, document: '' })
        }
      },
      () => {},
      { sleep, delays: [5, 7] },
    )

    expect(connections).toEqual([1, 2])
    expect(waits).toEqual([5])
  })
})
