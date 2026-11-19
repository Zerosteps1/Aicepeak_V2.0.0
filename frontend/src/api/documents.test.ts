import { describe, expect, it } from 'vitest'
import { json, stubApi } from '../test/fakeApi.ts'
import { deleteDocument, documentIdOf, requestUploadUrl, withoutQuery } from './documents.ts'

const REQUEST = { sha256: 'ab'.repeat(32), name: 'Jahresabschluss.pdf', size: 1024, contentType: 'application/pdf' }
const BLOB_URL = 'https://store.example/tenant/project/doc-1?sv=2025-01-05&sr=b&sp=c&sig=secret'

describe('requestUploadUrl', () => {
  it('AC-1: sends POST /project/{id}/upload-url with the file data and returns the upload URL', async () => {
    const api = stubApi()
    api.on('POST', '/project/p1/upload-url', () => json({ blobUrl: BLOB_URL, expires: '2026-11-19T10:15:00Z' }))

    const result = await requestUploadUrl('p1', REQUEST)

    expect(result).toEqual({ kind: 'upload', blobUrl: BLOB_URL, expires: '2026-11-19T10:15:00Z' })
    const [request] = api.sent('POST', '/project/p1/upload-url')
    expect(request?.headers.get('Content-Type')).toBe('application/json')
    expect(request?.body).toEqual(REQUEST)
  })

  it('returns the existing document for a duplicate', async () => {
    const document = { url: 'https://store.example/tenant/other/doc-9', name: REQUEST.name, size: 1024, contentType: 'application/pdf' }
    const api = stubApi()
    api.on('POST', '/project/p1/upload-url', () => json({ document }))

    await expect(requestUploadUrl('p1', REQUEST)).resolves.toEqual({ kind: 'existing', document })
  })

  it('AC-2: rejects with status 404 when the project is unknown', async () => {
    const api = stubApi()
    api.on('POST', '/project/p1/upload-url', () => new Response(null, { status: 404 }))

    await expect(requestUploadUrl('p1', REQUEST)).rejects.toMatchObject({ status: 404 })
  })

  it('rejects an answer with neither URL nor document', async () => {
    const api = stubApi()
    api.on('POST', '/project/p1/upload-url', () => json({}))

    await expect(requestUploadUrl('p1', REQUEST)).rejects.toThrow('neither blobUrl nor document')
  })
})

describe('deleteDocument', () => {
  it('AC-6: sends DELETE /project/{id}/document/{documentId}', async () => {
    const api = stubApi()
    api.on('DELETE', '/project/p1/document/doc-1', () => new Response(null, { status: 204 }))

    await deleteDocument('p1', 'doc-1')

    expect(api.sent('DELETE', '/project/p1/document/doc-1')).toHaveLength(1)
  })

  it('AC-6b: rejects with status 404 when the document is not linked', async () => {
    const api = stubApi()
    api.on('DELETE', '/project/p1/document/doc-1', () => new Response(null, { status: 404 }))

    await expect(deleteDocument('p1', 'doc-1')).rejects.toMatchObject({ status: 404 })
  })
})

describe('document URLs', () => {
  it('strips the signed query and any fragment', () => {
    expect(withoutQuery(BLOB_URL)).toBe('https://store.example/tenant/project/doc-1')
    expect(withoutQuery('https://store.example/t/p/d#x')).toBe('https://store.example/t/p/d')
    expect(withoutQuery('https://store.example/t/p/d')).toBe('https://store.example/t/p/d')
  })

  it('takes the documentId from the last path segment', () => {
    expect(documentIdOf(BLOB_URL)).toBe('doc-1')
    expect(documentIdOf('http://127.0.0.1:10000/devstoreaccount1/tenant/project/0195f3a2-0000-7000-8000-00000000000d')).toBe(
      '0195f3a2-0000-7000-8000-00000000000d',
    )
  })
})
