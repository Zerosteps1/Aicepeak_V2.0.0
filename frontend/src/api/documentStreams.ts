import { readEventStream } from './eventStream.ts'

/**
 * Data of an event of `GET /project/{id}/document-validation/sse`. `document` is the documentId the event is about,
 * or `''` for the whole run. `error` on a document means that document is invalid; with `document: ''` the whole run
 * failed. The event with `overallProgress: 100` comes once and is always the last.
 */
export type ValidationEvent = {
  /** 0–100 for the whole run. */
  overallProgress: number
  document: string
  /** 0–100 for `document`. */
  documentProgress?: number
  error?: string
}

/** A position the extraction found, for the latest-positions table. */
export type ExtractedPosition = {
  name: string
  value: string | number
  period: string
  source: string
  page: number
}

/** Data of an event of `GET /project/{id}/document-extraction/sse`; the fields of `ValidationEvent` mean the same. */
export type ExtractionEvent = ValidationEvent & {
  /** Pages of `document`. */
  pages?: number
  /** Pages of `document` read so far. */
  pagesRead?: number
  /** Positions found in the whole project so far. */
  positions?: number
  position?: ExtractedPosition
}

type Fields = Record<string, unknown>

function isFields(value: unknown): value is Fields {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/** Copies the optional field when it has the expected type; `null` counts as absent. Returns false for a wrong type. */
function copyOptional<T>(target: Fields, source: Fields, key: string, guard: (value: unknown) => value is T): boolean {
  const value = source[key]
  if (value === undefined || value === null) {
    return true
  }
  if (!guard(value)) {
    return false
  }
  target[key] = value
  return true
}

function isString(value: unknown): value is string {
  return typeof value === 'string'
}

/** Whether the value is an extracted position; its fields are required. */
export function isExtractedPosition(value: unknown): value is ExtractedPosition {
  return (
    isFields(value) &&
    isString(value.name) &&
    (isString(value.value) || isNumber(value.value)) &&
    isString(value.period) &&
    isString(value.source) &&
    isNumber(value.page)
  )
}

function validationFields(value: unknown): Fields | null {
  if (!isFields(value) || !isNumber(value.overallProgress) || !isString(value.document)) {
    return null
  }
  const event: Fields = { overallProgress: value.overallProgress, document: value.document }
  const ok = copyOptional(event, value, 'documentProgress', isNumber) && copyOptional(event, value, 'error', isString)
  return ok ? event : null
}

/** The validation event in `data` (JSON), with `null` fields left out; `null` when it does not match the contract. */
export function parseValidationEvent(data: string): ValidationEvent | null {
  try {
    return validationFields(JSON.parse(data)) as ValidationEvent | null
  } catch {
    return null
  }
}

/** The extraction event in `data` (JSON), with `null` fields left out; `null` when it does not match the contract. */
export function parseExtractionEvent(data: string): ExtractionEvent | null {
  try {
    const value: unknown = JSON.parse(data)
    const event = validationFields(value)
    if (!event || !isFields(value)) {
      return null
    }
    const ok =
      copyOptional(event, value, 'pages', isNumber) &&
      copyOptional(event, value, 'pagesRead', isNumber) &&
      copyOptional(event, value, 'positions', isNumber) &&
      copyOptional(event, value, 'position', isExtractedPosition)
    return ok ? (event as ExtractionEvent) : null
  } catch {
    return null
  }
}

/** Path of the validation stream of a project, for `readEventStream`. */
export function validationStreamPath(projectId: string): string {
  return `/project/${encodeURIComponent(projectId)}/document-validation/sse`
}

/** Path of the extraction stream of a project, for `readEventStream`. */
export function extractionStreamPath(projectId: string): string {
  return `/project/${encodeURIComponent(projectId)}/document-extraction/sse`
}

/**
 * Reads the validation stream of a project until it ends; see `readEventStream`. Calls `onEvent` for every `message`
 * event that matches the contract and skips the others.
 */
export function readValidationStream(
  projectId: string,
  onEvent: (event: ValidationEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return readEventStream(
    validationStreamPath(projectId),
    (event) => {
      const parsed = event.type === 'message' ? parseValidationEvent(event.data) : null
      if (parsed) {
        onEvent(parsed)
      }
    },
    signal,
  )
}

/** Reads the extraction stream of a project until it ends, like `readValidationStream`. */
export function readExtractionStream(
  projectId: string,
  onEvent: (event: ExtractionEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return readEventStream(
    extractionStreamPath(projectId),
    (event) => {
      const parsed = event.type === 'message' ? parseExtractionEvent(event.data) : null
      if (parsed) {
        onEvent(parsed)
      }
    },
    signal,
  )
}
