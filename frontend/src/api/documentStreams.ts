import { readEventStream } from './eventStream.ts'
import { ApiError } from './httpClient.ts'

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

/** The waits before the reconnects of a broken stream, in milliseconds: three reconnects, after 1 s, 3 s and 10 s. */
export const RECONNECT_DELAYS_MS: readonly number[] = [1000, 3000, 10_000]

/** One connection of a run's stream: calls `onEvent` for each event and settles like `readEventStream`. */
export type StreamConnection<E> = (onEvent: (event: E) => void, signal?: AbortSignal) => Promise<void>

/** How `readWithReconnect` reconnects. */
export type ReconnectOptions = {
  /** Aborts the reading, also while it waits to reconnect. */
  signal?: AbortSignal
  /**
   * Called once the wait before a reconnect is over, just before it (`attempt` counts from 1). The backend starts the
   * run again for every connection, so what the previous connection reported starts over.
   */
  onReconnect?: (attempt: number) => void
  /** The wait before each reconnect; their number is the number of reconnects. `RECONNECT_DELAYS_MS` by default. */
  delays?: readonly number[]
  /** Waits `ms` milliseconds and rejects with the abort reason once `signal` aborts; a timer by default. */
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>
}

/** Whether the event ends a run: the event with `overallProgress: 100`, or an error of the whole run. */
export function isFinalEvent(event: ValidationEvent): boolean {
  return event.overallProgress >= 100 || (event.document === '' && event.error !== undefined)
}

/**
 * Whether a stream that failed with `error` is worth reconnecting: a network error (fetch rejects, and a body breaks
 * off, with a `TypeError`, and so does the `AccessTokenProvider` when the network fails while it gets the token) or a
 * 5xx. A 4xx is not: asking again gets the same answer.
 */
export function isStreamBreak(error: unknown): boolean {
  return error instanceof ApiError ? error.status >= 500 : error instanceof TypeError
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason)
      return
    }
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal?.reason)
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/**
 * Reads a run's stream until its final event (`isFinalEvent`), reconnecting when the stream breaks: after a network
 * error, a 5xx or a stream that closes before its final event, it waits the next of `delays` and connects again,
 * through `apiFetch`, so with a fresh access token. A 4xx, an error of `onEvent` or an abort ends it at once, and so
 * does an error of the whole run the backend reports, since that is a final event.
 *
 * Resolves after the final event, or when the last connection closed early as well (the caller sees no final event);
 * rejects with the error of the last connection otherwise, and with the abort reason once `signal` aborts.
 */
export async function readWithReconnect<E extends ValidationEvent>(
  connect: StreamConnection<E>,
  onEvent: (event: E) => void,
  { signal, onReconnect, delays = RECONNECT_DELAYS_MS, sleep = wait }: ReconnectOptions = {},
): Promise<void> {
  for (let attempt = 0; ; attempt++) {
    if (attempt > 0) {
      await sleep(delays[attempt - 1], signal)
      signal?.throwIfAborted()
      onReconnect?.(attempt)
    }
    const connection = { final: false, failedInHandler: false }
    const handle = (event: E) => {
      connection.final ||= isFinalEvent(event)
      try {
        onEvent(event)
      } catch (error) {
        connection.failedInHandler = true
        throw error
      }
    }
    const lastAttempt = attempt >= delays.length
    try {
      await connect(handle, signal)
    } catch (error) {
      if (signal?.aborted || connection.failedInHandler) {
        throw error
      }
      if (connection.final) {
        return
      }
      if (lastAttempt || !isStreamBreak(error)) {
        throw error
      }
      continue
    }
    if (connection.final || lastAttempt) {
      return
    }
  }
}

/**
 * Reads the validation run of a project until its final event, reconnecting a broken stream; see `readWithReconnect`
 * and `readValidationStream`.
 */
export function readValidationRun(
  projectId: string,
  onEvent: (event: ValidationEvent) => void,
  options?: ReconnectOptions,
): Promise<void> {
  return readWithReconnect((handle, signal) => readValidationStream(projectId, handle, signal), onEvent, options)
}

/**
 * Reads the extraction run of a project until its final event, reconnecting a broken stream; see `readWithReconnect`
 * and `readExtractionStream`. Each reconnect starts the extraction over (`onReconnect`).
 */
export function readExtractionRun(
  projectId: string,
  onEvent: (event: ExtractionEvent) => void,
  options?: ReconnectOptions,
): Promise<void> {
  return readWithReconnect((handle, signal) => readExtractionStream(projectId, handle, signal), onEvent, options)
}
