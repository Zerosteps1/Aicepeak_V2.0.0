import { describe, expect, it } from 'vitest'
import { ACCEPT_ATTRIBUTE, contentTypeOf, extensionOf, fileRejection, MAX_FILE_SIZE, rejectionMessage } from './files.ts'

describe('fileRejection', () => {
  it.each(['a.pdf', 'b.doc', 'c.docx', 'd.xls', 'e.xlsx', 'Bericht.Q3.PDF'])('AC-19: accepts %s', (name) => {
    expect(fileRejection({ name, size: 1 })).toBeNull()
  })

  it.each(['a.txt', 'b.csv', 'pdf', 'c.pdf.exe', 'd.'])('AC-19: rejects the kind of %s', (name) => {
    expect(fileRejection({ name, size: 1 })).toBe('kind')
  })

  it('AC-19: takes 1 byte up to exactly 50 MiB and rejects empty and larger files', () => {
    expect(MAX_FILE_SIZE).toBe(52_428_800)
    expect(fileRejection({ name: 'a.pdf', size: MAX_FILE_SIZE })).toBeNull()
    expect(fileRejection({ name: 'a.pdf', size: MAX_FILE_SIZE + 1 })).toBe('tooLarge')
    expect(fileRejection({ name: 'a.pdf', size: 0 })).toBe('empty')
  })

  it.each([' leading.pdf', 'a b.docx', '..pdf', 'Prüfbericht – 2025.xlsx', '\ufeff.pdf'])('AC-19: accepts the name %j', (name) => {
    expect(fileRejection({ name, size: 1 })).toBeNull()
  })

  it.each(['.pdf', ' .pdf', '\t\u3000.docx', 'ordner/a.pdf', 'ordner\\a.pdf', 'a\u0000.pdf', 'zeile\n.xlsx', 'del\u007f.pdf', 'c1\u0085.xls'])(
    'AC-19: rejects the name %j as the backend does',
    (name) => {
      expect(fileRejection({ name, size: 1 })).toBe('invalidName')
    },
  )

  it('AC-19: takes names up to 200 characters', () => {
    expect(fileRejection({ name: `${'a'.repeat(196)}.pdf`, size: 1 })).toBeNull()
    expect(fileRejection({ name: `${'a'.repeat(197)}.pdf`, size: 1 })).toBe('nameTooLong')
  })
})

describe('file kinds', () => {
  it('maps each accepted extension to its content type', () => {
    expect(contentTypeOf('a.PDF')).toBe('application/pdf')
    expect(contentTypeOf('a.doc')).toBe('application/msword')
    expect(contentTypeOf('a.docx')).toBe('application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    expect(contentTypeOf('a.xls')).toBe('application/vnd.ms-excel')
    expect(contentTypeOf('a.xlsx')).toBe('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    expect(contentTypeOf('a.txt')).toBe('application/octet-stream')
  })

  it('gives the lower-case extension and the accept attribute', () => {
    expect(extensionOf('Plan.v3.XLSX')).toBe('xlsx')
    expect(extensionOf('README')).toBe('')
    expect(ACCEPT_ATTRIBUTE).toBe('.pdf,.doc,.docx,.xls,.xlsx')
  })

  it('names the rejected files in German', () => {
    expect(rejectionMessage(['a.txt', 'b.zip'])).toBe(
      'a.txt, b.zip: nur PDF-, Word- oder Excel-Dateien bis 50 MB und mit höchstens 200 Zeichen im Namen.',
    )
  })
})
