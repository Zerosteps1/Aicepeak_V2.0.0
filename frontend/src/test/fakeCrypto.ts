import { vi } from 'vitest'

/**
 * Stubs `crypto.subtle.digest` with a known "hash": the first 32 bytes of the input, zero-padded. Returns the stub.
 */
export function stubDigest() {
  const digest = vi.fn<SubtleCrypto['digest']>(async (_algorithm, data) => {
    const input = data instanceof ArrayBuffer ? new Uint8Array(data) : new Uint8Array(data.buffer, data.byteOffset, data.byteLength)
    const bytes = new Uint8Array(32)
    bytes.set(input.slice(0, 32))
    return bytes.buffer
  })
  vi.stubGlobal('crypto', { subtle: { digest } })
  return digest
}

/** The hex digest `stubDigest` gives for an ASCII text. */
export function fakeSha256(text: string): string {
  const hex = Array.from(text.slice(0, 32), (char) => char.charCodeAt(0).toString(16).padStart(2, '0')).join('')
  return hex.padEnd(64, '0')
}
