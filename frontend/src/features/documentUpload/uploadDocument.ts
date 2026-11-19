import { blobUploader, BlobUploadError } from '../../api/blobStorage/index.ts'
import { requestUploadUrl, withoutQuery, type UploadUrlRequest } from '../../api/documents.ts'
import type { DocumentRef } from '../../api/projects.ts'
import { contentTypeOf } from './files.ts'

/** Options of `uploadDocument`. */
export type UploadDocumentOptions = {
  /** Upload progress in percent (0–100). Starts again at 0 when a new URL is tried. */
  onProgress?: (percent: number) => void
  signal?: AbortSignal
  /** The current time in epoch milliseconds; for tests. */
  now?: () => number
}

/** The SHA-256 of the file's bytes as 64 lower-case hex digits, computed in the browser with `crypto.subtle`. */
export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

/**
 * Uploads one accepted file for a project and returns the `DocumentRef` to link with the next PATCH: the new blob's
 * URL without its signed query, or, for a duplicate the tenant already has, that document without any upload.
 *
 * Gets an upload URL, then uploads. It tries once more with a new URL (AC-18) when the URL had already expired before
 * the upload started, or when the storage refused it (401/403, or no answer before the file had fully gone out).
 * Expiry is never checked once the upload has started (AC-17); the last try leaves the decision to the storage.
 */
export async function uploadDocument(projectId: string, file: File, options: UploadDocumentOptions = {}): Promise<DocumentRef> {
  const { onProgress, signal, now = Date.now } = options
  signal?.throwIfAborted()
  const contentType = contentTypeOf(file.name)
  const request: UploadUrlRequest = { sha256: await sha256Hex(file), name: file.name, size: file.size, contentType }
  signal?.throwIfAborted()
  // Same bytes, typed with the content type that the upload-url request and the PATCH declare.
  const body = file.slice(0, file.size, contentType)

  for (let attempt = 1; ; attempt++) {
    const lastTry = attempt === 2
    const target = await requestUploadUrl(projectId, request, signal)
    if (target.kind === 'existing') {
      return target.document
    }
    if (!lastTry && Date.parse(target.expires) <= now()) {
      continue
    }
    onProgress?.(0)
    try {
      await blobUploader.upload(target.blobUrl, body, {
        signal,
        onProgress: (loaded, total) => onProgress?.(total > 0 ? Math.round((loaded / total) * 100) : 0),
      })
    } catch (error) {
      if (!lastTry && error instanceof BlobUploadError && error.rejected) {
        continue
      }
      throw error
    }
    onProgress?.(100)
    return { url: withoutQuery(target.blobUrl), name: file.name, size: file.size, contentType }
  }
}
