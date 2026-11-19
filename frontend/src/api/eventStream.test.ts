import { afterEach, describe, expect, it } from 'vitest'
import { FakeEventStream, stubApi } from '../test/fakeApi.ts'
import { setAccessTokenProvider } from './httpClient.ts'
import { createEventStreamParser, readEventStream, type ServerSentEvent } from './eventStream.ts'

function parse(...chunks: string[]): ServerSentEvent[] {
  const events: ServerSentEvent[] = []
  const parser = createEventStreamParser((event) => events.push(event))
  chunks.forEach((chunk) => parser.push(chunk))
  return events
}

afterEach(() => {
  setAccessTokenProvider(null)
})

describe('createEventStreamParser', () => {
  it('dispatches an event on a blank line with type message by default', () => {
    expect(parse('data: {"a":1}\n\n')).toEqual([{ type: 'message', data: '{"a":1}', lastEventId: '' }])
  })

  it('accepts CRLF, LF and CR line endings, also when split across chunks', () => {
    expect(parse('data: a\r', '\n\r', '\ndata: b\r\r', 'data: c\n', '\n')).toEqual([
      { type: 'message', data: 'a', lastEventId: '' },
      { type: 'message', data: 'b', lastEventId: '' },
      { type: 'message', data: 'c', lastEventId: '' },
    ])
  })

  it('joins data lines with line feeds and drops only one space after the colon', () => {
    expect(parse('data:first\ndata:  second\ndata\n\n')).toEqual([{ type: 'message', data: 'first\n second\n', lastEventId: '' }])
  })

  it('reads event and id fields, skips comments, a leading BOM and events without data', () => {
    const events = parse('﻿: keep-alive\n\n', 'event: progress\nid: 7\ndata: x\n\n', 'event: empty\n\n', 'data: y\n\n')

    expect(events).toEqual([
      { type: 'progress', data: 'x', lastEventId: '7' },
      { type: 'message', data: 'y', lastEventId: '7' },
    ])
  })

  it('splits a field across chunks and never dispatches an event the stream does not finish', () => {
    expect(parse('da', 'ta: par', 'tial\n', '\ndata: unfinished\n')).toEqual([{ type: 'message', data: 'partial', lastEventId: '' }])
  })
})

describe('readEventStream', () => {
  it('requests text/event-stream with the access token and decodes UTF-8 across chunks', async () => {
    const api = stubApi()
    const stream = new FakeEventStream()
    api.on('GET', '/project/p1/document-validation/sse', () => stream)
    setAccessTokenProvider(async () => 'token-1')
    const events: ServerSentEvent[] = []

    const reading = readEventStream('/project/p1/document-validation/sse', (event) => events.push(event))
    const bytes = new TextEncoder().encode('data: Prüfung\n\n')
    const insideUmlaut = bytes.indexOf(0xc3) + 1
    stream.pushBytes(bytes.slice(0, insideUmlaut))
    stream.pushBytes(bytes.slice(insideUmlaut))
    stream.end()
    await reading

    const [request] = api.sent('GET', '/project/p1/document-validation/sse')
    expect(request?.headers.get('Accept')).toBe('text/event-stream')
    expect(request?.headers.get('Authorization')).toBe('Bearer token-1')
    expect(events).toEqual([{ type: 'message', data: 'Prüfung', lastEventId: '' }])
  })

  it('rejects with the HTTP status when the backend refuses the stream', async () => {
    const api = stubApi()
    api.on('GET', '/project/p1/document-validation/sse', () => new Response(null, { status: 404 }))

    await expect(readEventStream('/project/p1/document-validation/sse', () => {})).rejects.toMatchObject({ status: 404 })
  })

  it('rejects with the abort reason and cancels the stream once the signal aborts', async () => {
    const api = stubApi()
    const stream = new FakeEventStream()
    api.on('GET', '/project/p1/document-extraction/sse', () => stream)
    const controller = new AbortController()
    const events: ServerSentEvent[] = []

    const reading = readEventStream('/project/p1/document-extraction/sse', (event) => events.push(event), controller.signal)
    stream.push({ overallProgress: 10, document: 'd1' })
    await expect.poll(() => events.length).toBe(1)
    controller.abort()

    await expect(reading).rejects.toMatchObject({ name: 'AbortError' })
    expect(stream.cancelled).toBe(true)
  })
})
