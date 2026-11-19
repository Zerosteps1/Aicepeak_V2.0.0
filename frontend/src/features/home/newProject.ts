import type { NewProject } from '../../api/projects.ts'

function twoDigits(value: number): string {
  return String(value).padStart(2, '0')
}

/**
 * The project that "Neues Projekt" creates: named `Neues Projekt dd.MM.yyyy HH:mm:ss`, starting today, open-ended and
 * without description. All in the browser's local time.
 */
export function newProjectDefaults(now: Date = new Date()): NewProject {
  const year = String(now.getFullYear()).padStart(4, '0')
  const month = twoDigits(now.getMonth() + 1)
  const day = twoDigits(now.getDate())
  const time = [now.getHours(), now.getMinutes(), now.getSeconds()].map(twoDigits).join(':')
  return {
    name: `Neues Projekt ${day}.${month}.${year} ${time}`,
    startDate: `${year}-${month}-${day}`,
    endDate: null,
    description: '',
  }
}
