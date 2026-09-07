// import.meta.env.BASE_URL always has a trailing slash (e.g. '/' or '/hirato/')
const API_BASE = `${import.meta.env.BASE_URL}api`.replace(/\/{2,}/g, '/')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Imported lazily to avoid a circular import between the auth store and this client.
  const { useAuthStore } = await import('../stores/auth')
  const auth = useAuthStore()

  const headers = new Headers(options.headers)
  if (auth.token) headers.set('Authorization', `Bearer ${auth.token}`)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })

  if (res.status === 401) {
    auth.logout()
    throw new ApiError(401, 'Session expired, please log in again.')
  }

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new ApiError(res.status, data.detail || res.statusText)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
  delete: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'DELETE', body: body ? JSON.stringify(body) : undefined }),
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}
