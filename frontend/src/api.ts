const API_BASE = ''

async function api<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...((opts?.headers as any) || {}) },
    ...opts,
  })
  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`)
  return res.json()
}

export const listPorts = () => api<{ ports: string[] }>('/api/ports')
export const connectPort = (port: string) => api<{ success: boolean; error?: string; data?: any }>('/api/connect', { method: 'POST', body: JSON.stringify({ port }) })
export const disconnectPort = () => api<{ success: boolean }>('/api/disconnect', { method: 'POST' })
export const getStatus = () => api<{ connected: boolean; port: string | null }>('/api/status')
export const listDevices = () => api<{ success: boolean; devices: any[] }>('/api/devices')
export const sendCommand = (ieee: string, action: string, endpoint?: number, params?: object) =>
  api<{correlation_id: string; status: string}>(`/api/devices/${ieee}/command`, {
    method: 'POST',
    body: JSON.stringify({ action, endpoint, params })
  })
export const renameDevice = (ieee: string, name: string) => api<any>(`/api/devices/${ieee}/rename`, { method: 'PATCH', body: JSON.stringify({ name }) })
export const permitJoin = (duration: number) => api<any>('/api/network/permit-join', { method: 'POST', body: JSON.stringify({ duration }) })
export const listScenarios = () => api<any[]>('/api/scenarios')
export const createScenario = (payload: any) => api<any>('/api/scenarios', { method: 'POST', body: JSON.stringify(payload) })
export const updateScenario = (id: number, payload: any) => api<any>(`/api/scenarios/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
export const deleteScenario = (id: number) => api<any>(`/api/scenarios/${id}`, { method: 'DELETE' })
export const triggerScenario = (id: number) => api<any>(`/api/scenarios/${id}/trigger`, { method: 'POST' })
export const reorderScenarios = (items: { id: number; sort_order: number }[]) => api<any>('/api/scenarios/reorder', { method: 'PATCH', body: JSON.stringify(items) })
