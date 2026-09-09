import { createAuthClient } from '@neondatabase/neon-js/auth'

const authUrl = import.meta.env.VITE_NEON_AUTH_URL
if (!authUrl) {
  throw new Error('VITE_NEON_AUTH_URL is required')
}

export const authClient = createAuthClient(authUrl)
