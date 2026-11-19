import { describe, expect, it } from 'vitest'
import { FakeEventStream, stubApi } from '../test/fakeApi.ts'
import {
  extractionStreamPath,
  parseExtractionEvent,
  parseValidationEvent,
  readExtractionStream,
  readValidationStream,
  validationStreamPath,
  type ExtractionEvent,
  type ValidationEvent,
} from './documentStreams.ts'

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
