/** Options of one upload. */
export type BlobUploadOptions = {
  /** Called as the request body goes out; `loaded` and `total` are bytes. */
  onProgress?: (loaded: number, total: number) => void
  /** Aborting it cancels the upload and rejects with the abort reason. */
  signal?: AbortSignal
}

/**
 * Uploads a file to the short-lived URL the backend issued (`POST /project/{id}/upload-url`). Provider-neutral: the
 * URL carries the authorization, and each provider's adapter adds the headers its storage needs. An uploader never
 * sends the app's access token. Resolves once the storage has accepted the whole file; the request's content type is
 * `file.type`.
 */
export type BlobUploader = {
  upload(url: string, file: Blob, options?: BlobUploadOptions): Promise<void>
}

/** An upload the storage did not accept. */
export class BlobUploadError extends Error {
  /** The HTTP status of the storage's answer; 0 when none arrived (network error, CORS). */
  readonly status: number
  /**
   * Whether the storage refused the URL before taking the file (401/403, or no answer before the file had fully gone
   * out), so another try with a new URL may succeed.
   */
  readonly rejected: boolean

  constructor(status: number, rejected: boolean) {
    super(status === 0 ? 'Blob upload failed without an answer' : `Blob upload failed with HTTP ${status}`)
    this.name = 'BlobUploadError'
    this.status = status
    this.rejected = rejected
  }
}
