import { apiFetch, ensureOk } from './httpClient.ts'

/** One event of a `text/event-stream`, as the WHATWG HTML standard dispatches it. */
export type ServerSentEvent = {
  /** The `event` field; `message` when the event has none. */
  type: string
  /** The `data` lines joined with line feeds. */
  data: string
  /** The last `id` field seen in the stream so far. */
  lastEventId: string
}

/** Takes the decoded text of an event stream chunk by chunk, in order. */
export type EventStreamParser = {
  push(text: string): void
}

/**
 * Parses an event stream as specified in "Server-sent events" of the WHATWG HTML standard ("Interpreting an event
 * stream"): lines end with CRLF, LF or CR, also when split across chunks; a leading BOM is skipped; `:` starts a
 * comment; one space after the colon is dropped; a blank line dispatches the event unless it has no data. An event
 * that the stream does not finish with a blank line is never dispatched.
 */
export function createEventStreamParser(onEvent: (event: ServerSentEvent) => void): EventStreamParser {
  let started = false
  let afterCarriageReturn = false
  let pending = ''
  let data = ''
  let type = ''
  let idBuffer = ''

  function dispatch() {
    const lastEventId = idBuffer
    if (data === '') {
      type = ''
      return
    }
    const event = { type: type || 'message', data: data.endsWith('\n') ? data.slice(0, -1) : data, lastEventId }
    data = ''
    type = ''
    onEvent(event)
  }

  function processLine(line: string) {
    if (line === '') {
      dispatch()
      return
    }
    if (line.startsWith(':')) {
      return
    }
    const colon = line.indexOf(':')
    const field = colon < 0 ? line : line.slice(0, colon)
    let value = colon < 0 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) {
      value = value.slice(1)
    }
    if (field === 'event') {
      type = value
    } else if (field === 'data') {
      data += `${value}\n`
    } else if (field === 'id' && !value.includes('\0')) {
      idBuffer = value
    }
    // `retry` and unknown fields are ignored: the caller decides about reconnecting.
  }

  return {
    push(chunk: string) {
      if (chunk === '') {
        return
      }
      let text = chunk
      if (!started) {
        started = true
        if (text.startsWith('﻿')) {
          text = text.slice(1)
        }
      }
      let index = 0
      // The LF of a CRLF whose CR ended the previous chunk.
      if (afterCarriageReturn && text.startsWith('\n')) {
        index = 1
      }
      afterCarriageReturn = false
      let lineStart = index
      for (; index < text.length; index++) {
        const char = text[index]
        if (char !== '\r' && char !== '\n') {
          continue
        }
        const line = pending + text.slice(lineStart, index)
        pending = ''
        if (char === '\r') {
          if (text[index + 1] === '\n') {
            index++
          } else if (index + 1 === text.length) {
            afterCarriageReturn = true
          }
        }
        lineStart = index + 1
        processLine(line)
      }
      pending += text.slice(lineStart)
    },
  }
}

/**
 * Reads a server-sent event stream of the API until it ends, calling `onEvent` for each event. Uses `apiFetch`, so
 * the request carries the access token (`EventSource` cannot send an Authorization header).
 * Resolves when the backend closes the stream; rejects with an `ApiError` for an error status and with the abort
 * reason once `signal` aborts.
 */
export async function readEventStream(
  path: string,
  onEvent: (event: ServerSentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiFetch(path, { headers: { Accept: 'text/event-stream' }, signal })
  await ensureOk(response, `GET ${path}`)
  if (!response.body) {
    throw new Error(`GET ${path} returned no body`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = createEventStreamParser(onEvent)
  const cancel = () => {
    reader.cancel(signal?.reason).catch(() => {})
  }
  signal?.addEventListener('abort', cancel, { once: true })
  try {
    for (;;) {
      signal?.throwIfAborted()
      const { done, value } = await reader.read()
      signal?.throwIfAborted()
      if (done) {
        break
      }
      parser.push(decoder.decode(value, { stream: true }))
    }
    parser.push(decoder.decode())
  } finally {
    signal?.removeEventListener('abort', cancel)
  }
}
