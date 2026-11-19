import { vi } from 'vitest'

/**
 * A stand-in for XMLHttpRequest with what a blob uploader uses: events on the request and on `upload`, headers and
 * the body as sent. Tests settle each request with `respond`, `failNetwork` or let the code `abort` it.
 */
export class FakeXhr extends EventTarget {
  readonly upload = new EventTarget()
  method = ''
  url = ''
  /** Request headers by lower-case name. */
  readonly headers = new Map<string, string>()
  body: unknown = null
  status = 0
  timeout = 0
  withCredentials = false
  sent = false
  aborted = false
  private bodySent = false

  open(method: string, url: string) {
    this.method = method
    this.url = url
  }

  setRequestHeader(name: string, value: string) {
    this.headers.set(name.toLowerCase(), value)
  }

  send(body: unknown = null) {
    this.body = body
    this.sent = true
  }

  abort() {
    this.aborted = true
    this.dispatchEvent(new ProgressEvent('abort'))
  }

  /** The storage has taken `loaded` of `total` bytes of the body. */
  progress(loaded: number, total: number) {
    this.upload.dispatchEvent(new ProgressEvent('progress', { lengthComputable: true, loaded, total }))
  }

  /** The whole body has gone out. */
  finishBody() {
    if (!this.bodySent) {
      this.bodySent = true
      this.upload.dispatchEvent(new ProgressEvent('load'))
    }
  }

  /** The storage answers with `status` after taking the whole body. */
  respond(status: number) {
    this.finishBody()
    this.status = status
    this.dispatchEvent(new ProgressEvent('load'))
  }

  /** No answer arrives (network error or CORS); `afterBody` says whether the body had fully gone out. */
  failNetwork({ afterBody = false } = {}) {
    if (afterBody) {
      this.finishBody()
    }
    this.status = 0
    this.dispatchEvent(new ProgressEvent('error'))
  }
}

/** Replaces XMLHttpRequest for the test; `requests` lists every request created, oldest first. */
export function stubXhr() {
  const requests: FakeXhr[] = []
  class RecordedXhr extends FakeXhr {
    constructor() {
      super()
      requests.push(this)
    }
  }
  vi.stubGlobal('XMLHttpRequest', RecordedXhr)
  return {
    requests,
    /** The requests that have been sent and not settled or aborted yet. */
    open: () => requests.filter((request) => request.sent && !request.aborted && request.status === 0),
  }
}
