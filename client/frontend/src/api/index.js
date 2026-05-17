import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// ── Recordings ──────────────────────────────
export const getRecordings = (date) =>
  api.get('/recordings', { params: date ? { date } : {} }).then(r => r.data)

export const getRecording = (id) =>
  api.get(`/recordings/${id}`).then(r => r.data)

export const getVideoUrl = (id) => `/api/recordings/${id}/video`

export const deleteRecording = (id) =>
  api.delete(`/recordings/${id}`).then(r => r.data)

// ── Logs ────────────────────────────────────
export const getLogs = (period = 'day') =>
  api.get('/logs', { params: { period } }).then(r => r.data)

export const getLog = (id) =>
  api.get(`/logs/${id}`).then(r => r.data)

// ── Settings ────────────────────────────────
export const getSettings = () =>
  api.get('/settings').then(r => r.data)

export const updateSettings = (payload) =>
  api.put('/settings', payload).then(r => r.data)
