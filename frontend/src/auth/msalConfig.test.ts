import { BrowserCacheLocation } from '@azure/msal-browser'
import { afterEach, describe, expect, it } from 'vitest'
import { createMsalInstance, hasAuthResponse } from './msalConfig.ts'

afterEach(() => {
  delete window.__AICEPEAK_CONFIG__
})

describe('createMsalInstance', () => {
  it('AC-2: configures MSAL for the Microsoft Entra organizations authority with the redirect URI <origin>/login', () => {
    window.__AICEPEAK_CONFIG__ = { clientId: 'spa-client-id', apiScope: 'api://spa-client-id/access_as_user' }

    const { auth, cache } = createMsalInstance().getConfiguration()

    expect(auth.clientId).toBe('spa-client-id')
    expect(auth.authority).toBe('https://login.microsoftonline.com/organizations')
    expect(auth.redirectUri).toBe(`${window.location.origin}/login`)
    expect(cache.cacheLocation).toBe(BrowserCacheLocation.SessionStorage)
  })
})

describe('hasAuthResponse', () => {
  it.each([
    ['#code=abc&state=xyz', true],
    ['#error=access_denied&state=xyz', true],
    ['', false],
    ['#state=xyz', false],
    ['#section', false],
  ])('tells whether the URL fragment %j holds a response from Microsoft', (hash, expected) => {
    expect(hasAuthResponse(hash)).toBe(expected)
  })
})
