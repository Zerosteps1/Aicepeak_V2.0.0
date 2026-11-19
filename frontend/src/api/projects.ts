import { apiFetch, ensureOk, JSON_HEADERS } from './httpClient.ts'

/**
 * A document as the API shows it, always embedded in its project. Documents never change.
 * `url` is `<endpoint>/<tid>/<projectId>/<documentId>` without a query; its last path segment is the documentId.
 */
export type DocumentRef = {
  url: string
  name: string
  /** Bytes. */
  size: number
  contentType: string
}

/** A forecast project of the signed-in user's tenant. */
export type Project = {
  id: string
  name: string
  /** `yyyy-MM-dd`. */
  startDate: string
  /** `yyyy-MM-dd`, or `null` when open-ended. */
  endDate: string | null
  description: string
  documents: DocumentRef[]
}

/** The body of `POST /project`; the backend assigns `id`, and documents are added with a PATCH. */
export type NewProject = {
  name: string
  startDate: string
  endDate?: string | null
  description?: string
}

/**
 * The body of `PATCH /project/{id}`: only the given properties change, `endDate: null` clears the end date.
 * `documents` only ever adds documents; removing one is `deleteDocument`.
 */
export type ProjectPatch = {
  name?: string
  startDate?: string
  endDate?: string | null
  description?: string
  documents?: DocumentRef[]
}

function projectPath(id: string): string {
  return `/project/${encodeURIComponent(id)}`
}

/** Creates a project (201) and returns it. */
export async function createProject(project: NewProject, signal?: AbortSignal): Promise<Project> {
  const response = await apiFetch('/project', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(project), signal })
  await ensureOk(response, 'POST /project')
  return (await response.json()) as Project
}

/** Loads a project; an unknown id rejects with an `ApiError` with status 404. */
export async function getProject(id: string, signal?: AbortSignal): Promise<Project> {
  const response = await apiFetch(projectPath(id), { signal })
  await ensureOk(response, 'GET /project/{id}')
  return (await response.json()) as Project
}

/** Changes the given properties of a project and returns the project as the backend stored it. */
export async function patchProject(id: string, patch: ProjectPatch, signal?: AbortSignal): Promise<Project> {
  const response = await apiFetch(projectPath(id), {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(patch),
    signal,
  })
  await ensureOk(response, 'PATCH /project/{id}')
  return (await response.json()) as Project
}
