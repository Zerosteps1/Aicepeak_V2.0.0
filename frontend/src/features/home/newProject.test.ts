import { describe, expect, it } from 'vitest'
import { newProjectDefaults } from './newProject.ts'

describe('newProjectDefaults', () => {
  it('names the project after the local date and time, starts today and leaves the end open', () => {
    expect(newProjectDefaults(new Date(2026, 0, 5, 7, 8, 9))).toEqual({
      name: 'Neues Projekt 05.01.2026 07:08:09',
      startDate: '2026-01-05',
      endDate: null,
      description: '',
    })
  })

  it('uses the local date, not the UTC one', () => {
    const lateEvening = new Date(2026, 11, 31, 23, 59, 59)

    expect(newProjectDefaults(lateEvening).startDate).toBe('2026-12-31')
  })
})
