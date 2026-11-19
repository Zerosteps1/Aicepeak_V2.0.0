import { azureBlobUploader } from './azureBlobUploader.ts'
import type { BlobUploader } from './blobUploader.ts'

export { BlobUploadError, type BlobUploader, type BlobUploadOptions } from './blobUploader.ts'

/**
 * The uploader of the blob storage provider: the only place that picks the provider. It must match the backend's
 * `BLOB_PROVIDER`, which issues the upload URLs; Azure is the only provider today. Another provider (e.g. AWS S3) is
 * a new adapter next to `azureBlobUploader.ts`, selected here, without changes to callers.
 */
export const blobUploader: BlobUploader = azureBlobUploader
