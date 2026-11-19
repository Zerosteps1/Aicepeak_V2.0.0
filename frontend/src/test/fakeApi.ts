import { vi } from 'vitest'
import { deferred } from './deferred.ts'

/** A request the app sent to the backend, path relative to `/api/v1`. */
export type RecordedRequest = {
  method: string
  path: string
  headers: Headers
  /** The JSON body parsed; `undefined` without one. */
  body: unknown
  signal: AbortSignal | null
}

type Reply = Response | FakeEventStream
type Handler = (request: RecordedRequest) => Reply | Promise<Reply>

const encoder = new TextEncoder()

/**
 * A `text/event-stream` body the test writes to. Its reader is made by hand: a Response built around a ReadableStream
 * of the test realm does not always pass between jsdom and Node's fetch classes.
 */
export class FakeEventStream {
  private chunks: Uint8Array[] = []
  private waiting: ReturnType<typeof deferred<ReadableStreamReadResult<Uint8Array>>> | null = null
  private ended = false
  private failure: unknown = null
  /** Set when the reader was cancelled or the request aborted. */
  cancelled = false

  /** Sends an event: an object as `data: <JSON>` with a blank line, a string as raw text. */
  push(event: object | string) {
    this.write(typeof event === 'string' ? event : `data: ${JSON.stringify(event)}\n\n`)
  }

  /** Sends raw bytes, e.g. half of a multi-byte character. */
  pushBytes(bytes: Uint8Array) {
    this.chunks.push(bytes)
    this.flush()
  }

  /** The backend closes the stream. */
  end() {
    this.ended = true
    this.flush()
  }

  /** The connection breaks. */
  fail(error: unknown = new TypeError('network error')) {
    this.failure = error
    this.flush()
  }

  /** What `fetch` resolves with; reading rejects once `signal` aborts, as with a real fetch. */
  response(signal: AbortSignal | null): Response {
    signal?.addEventListener('abort', () => {
      this.cancelled = true
      this.fail(signal.reason)
    })
    const reader = {
      read: () => this.read(),
      cancel: async () => {
        this.cancelled = true
        this.end()
      },
      releaseLock: () => {},
    }
    return {
      ok: true,
      status: 200,
      headers: new Headers({ 'Content-Type': 'text/event-stream' }),
      body: { getReader: () => reader },
    } as unknown as Response
  }

  private write(text: string) {
    this.pushBytes(encoder.encode(text))
  }

  private read(): Promise<ReadableStreamReadResult<Uint8Array>> {
    const next = this.next()
    if (next) {
      return next
    }
    this.waiting = deferred<ReadableStreamReadResult<Uint8Array>>()
    return this.waiting.promise
  }

  private next(): Promise<ReadableStreamReadResult<Uint8Array>> | null {
    if (this.failure !== null) {
      return Promise.reject(this.failure)
    }
    const chunk = this.chunks.shift()
    if (chunk) {
      return Promise.resolve({ done: false, value: chunk })
    }
    return this.ended ? Promise.resolve({ done: true, value: undefined }) : null
  }

  private flush() {
    const waiting = this.waiting
    const next = waiting && this.next()
    if (waiting && next) {
      this.waiting = null
      next.then(waiting.resolve, waiting.reject)
    }
  }
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') {
    return undefined
  }
  try {
    return JSON.parse(body)
  } catch {
    return body
  }
}

/**
 * Replaces `fetch` with a backend whose routes the test defines. A route is a method and a path (relative to
 * `/api/v1`) or a pattern; the route registered last wins. Unknown routes answer 599 so a test sees them.
 */
export function stubApi() {
  const routes: Array<{ method: string; path: string | RegExp; handler: Handler }> = []
  const requests: RecordedRequest[] = []

  const fetchMock = vi.fn<typeof fetch>(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const request: RecordedRequest = {
      method: init.method ?? 'GET',
      path: url.replace(/^\/api\/v1/, ''),
      headers: new Headers(init.headers),
      body: parseBody(init.body),
      signal: init.signal ?? null,
    }
    requests.push(request)
    if (request.signal?.aborted) {
      throw request.signal.reason
    }
    const route = [...routes]
      .reverse()
      .find((candidate) =>
        candidate.method === request.method &&
        (typeof candidate.path === 'string' ? candidate.path === request.path : candidate.path.test(request.path)),
      )
    if (!route) {
      return new Response(`No route for ${request.method} ${request.path}`, { status: 599 })
    }
    const reply = await route.handler(request)
    return reply instanceof FakeEventStream ? reply.response(request.signal) : reply
  })
  vi.stubGlobal('fetch', fetchMock)

  return {
    requests,
    fetch: fetchMock,
    on(method: string, path: string | RegExp, handler: Handler) {
      routes.push({ method, path, handler })
    },
    /** Answers every request to the route with a new event stream; the returned list fills as requests arrive. */
    streams(path: string | RegExp) {
      const streams: FakeEventStream[] = []
      routes.push({
        method: 'GET',
        path,
        handler: () => {
          const stream = new FakeEventStream()
          streams.push(stream)
          return stream
        },
      })
      return streams
    },
    /** The requests sent with `method` to `path` so far. */
    sent(method: string, path: string | RegExp) {
      return requests.filter(
        (request) =>
          request.method === method && (typeof path === 'string' ? request.path === path : path.test(request.path)),
      )
    },
  }
}

/** A JSON response, `200` unless told otherwise. */
export function json(body: unknown, status = 200): Response {
  return Response.json(body, { status })
}

/** A ValidationProblem response (400) with the given field errors. */
export function validationProblem(errors: Record<string, string[]>): Response {
  return new Response(JSON.stringify({ title: 'One or more validation errors occurred.', status: 400, errors }), {
    status: 400,
    headers: { 'Content-Type': 'application/problem+json' },
  })
}
