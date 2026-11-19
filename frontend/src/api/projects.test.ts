import { afterEach, describe, expect, it } from 'vitest'
import { json, stubApi, validationProblem } from '../test/fakeApi.ts'
import { ApiError, setAccessTokenProvider } from './httpClient.ts'
import { createProject, getProject, patchProject, type Project } from './projects.ts'

const PROJECT: Project = {
  id: '0195f3a2-0000-7000-8000-000000000001',
  name: 'Neues Projekt 19.11.2026 10:15:00',
  startDate: '2026-11-19',
  endDate: null,
  description: '',
  documents: [],
}

afterEach(() => {
  setAccessTokenProvider(null)
})

describe('createProject', () => {
  it('AC-13: sends POST /project as JSON with the access token and returns the created project', async () => {
    const api = stubApi()
    api.on('POST', '/project', () => json(PROJECT, 201))
    setAccessTokenProvider(async () => 'token-1')

    const project = await createProject({ name: PROJECT.name, startDate: '2026-11-19', endDate: null, description: '' })

    expect(project).toEqual(PROJECT)
    const [request] = api.sent('POST', '/project')
    expect(request?.headers.get('Content-Type')).toBe('application/json')
    expect(request?.headers.get('Authorization')).toBe('Bearer token-1')
    expect(request?.body).toEqual({ name: PROJECT.name, startDate: '2026-11-19', endDate: null, description: '' })
  })

  it('AC-5: rejects with the field errors of a 400', async () => {
    const api = stubApi()
    api.on('POST', '/project', () => validationProblem({ name: ['already exists'] }))

    await expect(createProject({ name: 'Doppelt', startDate: '2026-11-19' })).rejects.toMatchObject({
      status: 400,
      errors: { name: ['already exists'] },
    })
  })
})

describe('getProject', () => {
  it('AC-13: loads GET /project/{id}', async () => {
    const api = stubApi()
    api.on('GET', `/project/${PROJECT.id}`, () => json(PROJECT))

    await expect(getProject(PROJECT.id)).resolves.toEqual(PROJECT)
  })

  it('AC-2: rejects with an ApiError with status 404 for an unknown project', async () => {
    const api = stubApi()
    api.on('GET', '/project/unknown', () => new Response(null, { status: 404 }))

    const error = await getProject('unknown').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404 })
  })
})

describe('patchProject', () => {
  it('AC-4: sends PATCH /project/{id} with Content-Type application/json and returns the stored project', async () => {
    const api = stubApi()
    const document = { url: 'https://store.example/t/p/d1', name: 'a.pdf', size: 3, contentType: 'application/pdf' }
    api.on('PATCH', `/project/${PROJECT.id}`, () => json({ ...PROJECT, documents: [document] }))

    const project = await patchProject(PROJECT.id, { documents: [document], endDate: null })

    expect(project.documents).toEqual([document])
    const [request] = api.sent('PATCH', `/project/${PROJECT.id}`)
    expect(request?.headers.get('Content-Type')).toBe('application/json')
    expect(request?.body).toEqual({ documents: [document], endDate: null })
  })

  it('AC-15: rejects with every field error of a 400', async () => {
    const api = stubApi()
    api.on('PATCH', `/project/${PROJECT.id}`, () =>
      validationProblem({ 'documents[0].url': ['must not have a query'], 'documents[1].size': ['does not match the uploaded file'] }),
    )

    await expect(patchProject(PROJECT.id, { documents: [] })).rejects.toMatchObject({
      status: 400,
      errors: { 'documents[0].url': ['must not have a query'], 'documents[1].size': ['does not match the uploaded file'] },
    })
  })
})
