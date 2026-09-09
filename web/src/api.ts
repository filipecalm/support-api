import { authClient } from './auth'

const apiBase = (import.meta.env.VITE_SUPPORT_API_URL || '').replace(/\/$/, '')
if (!apiBase) {
  throw new Error('VITE_SUPPORT_API_URL is required')
}

export type Role = 'CUSTOMER' | 'AGENT' | 'ADMIN'
export type Status = 'OPEN' | 'IN_PROGRESS' | 'WAITING_CUSTOMER' | 'RESOLVED'
export type Priority = 'LOW' | 'NORMAL' | 'HIGH'

export type Me = { id: string; name: string; role: Role }
export type Ticket = {
  id: string
  customer_id: string
  assignee_id: string | null
  title: string
  description: string
  category: string
  priority: Priority
  status: Status
  version: number
  created_at: string
}
export type Comment = {
  id: string
  ticket_id: string
  author_id: string
  body: string
  internal: boolean
  created_at: string
}
export type EventItem = {
  id: string
  ticket_id: string
  actor_id: string
  action: string
  internal: boolean
  created_at: string
}
export type Page<T> = { items: T[]; total: number; page: number; size: number }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function bearer(): Promise<string> {
  const maybeJwt = (
    authClient as { getJWTToken?: () => Promise<string | null> }
  ).getJWTToken
  if (typeof maybeJwt === 'function') {
    const token = await maybeJwt.call(authClient)
    if (!token) throw new ApiError(401, 'Missing Neon Auth JWT')
    return token
  }
  const { data, error } = await authClient.token()
  if (error || !data?.token) {
    throw new ApiError(401, error?.message || 'Missing Neon Auth JWT')
  }
  return data.token
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await bearer()
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(`${apiBase}${path}`, { ...init, headers })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  me: () => request<Me>('/v1/me'),
  listTickets: (params: URLSearchParams) =>
    request<Page<Ticket>>(`/v1/tickets?${params}`),
  getTicket: (id: string) => request<Ticket>(`/v1/tickets/${id}`),
  createTicket: (payload: {
    title: string
    description: string
    category: string
    priority: Priority
  }) =>
    request<Ticket>('/v1/tickets', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  changeTicket: (
    id: string,
    payload: {
      expected_version: number
      status?: Status
      assignee_id?: string | null
    },
  ) =>
    request<Ticket>(`/v1/tickets/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  listComments: (id: string) =>
    request<Page<Comment>>(`/v1/tickets/${id}/comments?page=1&size=50`),
  addComment: (id: string, payload: { body: string; internal?: boolean }) =>
    request<Comment>(`/v1/tickets/${id}/comments`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listEvents: (id: string) =>
    request<Page<EventItem>>(`/v1/tickets/${id}/events?page=1&size=50`),
}
