import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubXhr } from '../../test/fakeXhr.ts'
import { setAccessTokenProvider } from '../httpClient.ts'
import { azureBlobUploader } from './azureBlobUploader.ts'
import { BlobUploadError } from './blobUploader.ts'
import { blobUploader } from './index.ts'

const SAS_URL = 'https://store.example/tenant/project/doc-1?sv=2025-01-05&sr=b&sp=c&sig=secret'

function file(type = 'application/pdf') {
  return new Blob(['%PDF-1.7'], { type })
}

afterEach(() => {
  setAccessTokenProvider(null)
})

describe('azureBlobUploader', () => {
  it('is the provider the app uses', () => {
    expect(blobUploader).toBe(azureBlobUploader)
  })

  it('AC-3: PUTs the file to the SAS SAS_URL as is, as a block blob with its content type and without Authorization', async () => {
    const xhr = stubXhr()
    setAccessTokenProvider(async () => 'app-token')
    const body = file()

    const upload = azureBlobUploader.upload(SAS_URL, body)
    const [request] = xhr.requests
    request?.respond(201)
    await upload

    expect(request?.method).toBe('PUT')
    expect(request?.url).toBe(SAS_URL)
    expect(request?.body).toBe(body)
    expect(Object.fromEntries(request?.headers ?? [])).toEqual({
      'x-ms-blob-type': 'BlockBlob',
      'content-type': 'application/pdf',
    })
    expect(request?.withCredentials).toBe(false)
  })

  it('falls back to application/octet-stream for an untyped file', async () => {
    const xhr = stubXhr()

    const upload = azureBlobUploader.upload(SAS_URL, file(''))
    xhr.requests[0]?.respond(201)
    await upload

    expect(xhr.requests[0]?.headers.get('content-type')).toBe('application/octet-stream')
  })

  it('reports upload progress in bytes', async () => {
    const xhr = stubXhr()
    const onProgress = vi.fn<(loaded: number, total: number) => void>()

    const upload = azureBlobUploader.upload(SAS_URL, file(), { onProgress })
    xhr.requests[0]?.progress(4, 8)
    xhr.requests[0]?.respond(201)
    await upload

    expect(onProgress).toHaveBeenCalledWith(4, 8)
  })

  it.each([401, 403])('AC-18: marks HTTP %i as a refused SAS_URL', async (status) => {
    const xhr = stubXhr()

    const upload = azureBlobUploader.upload(SAS_URL, file())
    xhr.requests[0]?.respond(status)

    await expect(upload).rejects.toEqual(new BlobUploadError(status, true))
    await expect(upload).rejects.toMatchObject({ status, rejected: true })
  })

  it('does not mark other errors as a refused SAS_URL', async () => {
    const xhr = stubXhr()

    const upload = azureBlobUploader.upload(SAS_URL, file())
    xhr.requests[0]?.respond(500)

    await expect(upload).rejects.toMatchObject({ status: 500, rejected: false })
  })

  it('AC-18: no answer before the file has fully gone out is a refused SAS_URL, after it is not', async () => {
    const xhr = stubXhr()

    const early = azureBlobUploader.upload(SAS_URL, file())
    xhr.requests[0]?.failNetwork()
    const late = azureBlobUploader.upload(SAS_URL, file())
    xhr.requests[1]?.failNetwork({ afterBody: true })

    await expect(early).rejects.toMatchObject({ status: 0, rejected: true })
    await expect(late).rejects.toMatchObject({ status: 0, rejected: false })
  })

  it('aborts the request when the signal aborts', async () => {
    const xhr = stubXhr()
    const controller = new AbortController()

    const upload = azureBlobUploader.upload(SAS_URL, file(), { signal: controller.signal })
    controller.abort()

    await expect(upload).rejects.toMatchObject({ name: 'AbortError' })
    expect(xhr.requests[0]?.aborted).toBe(true)
  })

  it('sends nothing when the signal has already aborted', async () => {
    const xhr = stubXhr()
    const controller = new AbortController()
    controller.abort()

    await expect(azureBlobUploader.upload(SAS_URL, file(), { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
    expect(xhr.requests).toHaveLength(0)
  })
})
