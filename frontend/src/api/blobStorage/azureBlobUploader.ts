import { BlobUploadError, type BlobUploader } from './blobUploader.ts'

/**
 * The Azure Blob Storage adapter: one `Put Blob` with the SAS URL as is, `x-ms-blob-type: BlockBlob` and the file's
 * content type. Uses XMLHttpRequest because fetch reports no upload progress. Sends no Authorization header and no
 * cookies: the SAS in the URL is the only credential.
 */
export const azureBlobUploader: BlobUploader = {
  upload(url, file, { onProgress, signal } = {}) {
    return new Promise<void>((resolve, reject) => {
      if (signal?.aborted) {
        reject(signal.reason)
        return
      }
      const xhr = new XMLHttpRequest()
      // Set once the request body has fully gone out; a later failure is no longer a refused URL.
      let sent = false

      const onAbort = () => xhr.abort()
      const settle = () => signal?.removeEventListener('abort', onAbort)

      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable) {
          onProgress?.(event.loaded, event.total)
        }
      })
      xhr.upload.addEventListener('load', () => {
        sent = true
      })
      xhr.addEventListener('load', () => {
        settle()
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve()
        } else {
          reject(new BlobUploadError(xhr.status, xhr.status === 401 || xhr.status === 403))
        }
      })
      xhr.addEventListener('error', () => {
        settle()
        reject(new BlobUploadError(0, !sent))
      })
      xhr.addEventListener('timeout', () => {
        settle()
        reject(new BlobUploadError(0, false))
      })
      xhr.addEventListener('abort', () => {
        settle()
        reject(signal?.reason ?? new DOMException('The upload was aborted.', 'AbortError'))
      })
      signal?.addEventListener('abort', onAbort, { once: true })

      xhr.open('PUT', url)
      xhr.setRequestHeader('x-ms-blob-type', 'BlockBlob')
      xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream')
      xhr.send(file)
    })
  },
}
