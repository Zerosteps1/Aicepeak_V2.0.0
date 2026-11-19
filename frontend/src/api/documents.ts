import { apiFetch, ensureOk, JSON_HEADERS } from './httpClient.ts'
import type { DocumentRef } from './projects.ts'

/** What `POST /project/{id}/upload-url` needs to know about a file. */
export type UploadUrlRequest = {
  /** SHA-256 of the file's bytes, 64 lower-case hex digits; used only to find a duplicate. */
  sha256: string
  name: string
  /** Bytes. */
  size: number
  contentType: string
}

/**
 * The answer of `POST /project/{id}/upload-url`: either a short-lived URL to upload the file to, or, when the tenant
 * already has a document with the same SHA-256, name and size, that document, so the upload is skipped.
 */
export type UploadUrlResult =
  | {
      kind: 'upload'
      /** The signed URL for the PUT, used as is. */
      blobUrl: string
      /** When the URL stops working, as an ISO 8601 timestamp. */
      expires: string
    }
  | { kind: 'existing'; document: DocumentRef }

function projectPath(projectId: string): string {
  return `/project/${encodeURIComponent(projectId)}`
}

/** Asks for an upload URL for one file, or the document the tenant already has with the same content. */
export async function requestUploadUrl(
  projectId: string,
  request: UploadUrlRequest,
  signal?: AbortSignal,
): Promise<UploadUrlResult> {
  const response = await apiFetch(`${projectPath(projectId)}/upload-url`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(request),
    signal,
  })
  await ensureOk(response, 'POST /project/{id}/upload-url')
  const body = (await response.json()) as { blobUrl?: unknown; expires?: unknown; document?: DocumentRef | null }
  if (body.document) {
    return { kind: 'existing', document: body.document }
  }
  if (typeof body.blobUrl === 'string' && typeof body.expires === 'string') {
    return { kind: 'upload', blobUrl: body.blobUrl, expires: body.expires }
  }
  throw new Error('POST /project/{id}/upload-url returned neither blobUrl nor document')
}

/**
 * Removes the document from the project (204). The backend deletes the document itself only once no project links it.
 * A 404 means the project is missing or the document is not linked to it; then nothing changed.
 */
export async function deleteDocument(projectId: string, documentId: string, signal?: AbortSignal): Promise<void> {
  const response = await apiFetch(`${projectPath(projectId)}/document/${encodeURIComponent(documentId)}`, {
    method: 'DELETE',
    signal,
  })
  await ensureOk(response, 'DELETE /project/{id}/document/{documentId}')
}

/** The URL without its query and fragment, i.e. without the signature of an upload URL. */
export function withoutQuery(url: string): string {
  return url.split(/[?#]/, 1)[0] ?? ''
}

/** The documentId of a document or upload URL: its last path segment. */
export function documentIdOf(url: string): string {
  const path = withoutQuery(url)
  return path.slice(path.lastIndexOf('/') + 1)
}
