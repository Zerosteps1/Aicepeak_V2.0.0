/** The content type sent for each accepted extension; the backend compares it with the stored blob's. */
const CONTENT_TYPES = {
  pdf: 'application/pdf',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
} as const

type AcceptedExtension = keyof typeof CONTENT_TYPES

/** The file kinds a project takes: PDF, Word and Excel. */
export const ACCEPTED_EXTENSIONS = Object.keys(CONTENT_TYPES) as AcceptedExtension[]

/** For the `accept` attribute of a file input. */
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.map((extension) => `.${extension}`).join(',')

/** 50 MiB, the backend's limit (52 428 800 bytes). */
export const MAX_FILE_SIZE = 50 * 1024 * 1024

/** The longest file name the backend takes. */
export const MAX_NAME_LENGTH = 200

/**
 * Why a file cannot be added. `invalidName`: the name holds a control character, `/` or `\\`, or nothing but
 * whitespace before the extension; the backend takes no such name.
 */
export type FileRejection = 'kind' | 'empty' | 'tooLarge' | 'nameTooLong' | 'invalidName'

/** The lower-case extension of a file name, without the dot; `''` when it has none. */
export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot + 1).toLowerCase()
}

function isAccepted(extension: string): extension is AcceptedExtension {
  return Object.hasOwn(CONTENT_TYPES, extension)
}

/** Nothing but what the backend counts as whitespace (.NET `char.IsWhiteSpace`); also matches `''`. */
const ONLY_WHITESPACE = /^[\t\n\v\f\r \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/

/** Control characters as the backend counts them (.NET `char.IsControl`: U+0000–U+001F, U+007F–U+009F). */
function isControl(character: string): boolean {
  const code = character.charCodeAt(0)
  return code <= 0x1f || (code >= 0x7f && code <= 0x9f)
}

/**
 * Whether the backend takes the name of a file with an accepted extension: a file name only (no `/` or `\\`), no
 * control characters, and something other than whitespace before the extension (`.pdf` and ` .pdf` are no names).
 */
function isValidName(name: string): boolean {
  if ([...name].some((character) => isControl(character) || character === '/' || character === '\\')) {
    return false
  }
  return !ONLY_WHITESPACE.test(name.slice(0, name.lastIndexOf('.')))
}

/** Why the file cannot be added, or `null` when it can (AC-19: rejected files cause no request). */
export function fileRejection(file: { name: string; size: number }): FileRejection | null {
  if (!isAccepted(extensionOf(file.name))) {
    return 'kind'
  }
  if (file.size <= 0) {
    return 'empty'
  }
  if (file.size > MAX_FILE_SIZE) {
    return 'tooLarge'
  }
  if (file.name.length > MAX_NAME_LENGTH) {
    return 'nameTooLong'
  }
  if (!isValidName(file.name)) {
    return 'invalidName'
  }
  return null
}

/** The content type for an accepted file name, from its extension; `application/octet-stream` for any other. */
export function contentTypeOf(name: string): string {
  const extension = extensionOf(name)
  return isAccepted(extension) ? CONTENT_TYPES[extension] : 'application/octet-stream'
}

/** The message for files that were not added, naming them; ready to show. */
export function rejectionMessage(names: readonly string[]): string {
  return `${names.join(', ')}: nur PDF-, Word- oder Excel-Dateien bis 50 MB und mit höchstens ${MAX_NAME_LENGTH} Zeichen im Namen.`
}
