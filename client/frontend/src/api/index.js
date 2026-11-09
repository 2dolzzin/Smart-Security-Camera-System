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
export const getLogs = (period = 'day', anomalyOnly = false, type = null) =>
  api.get('/logs', { params: { period, ...(anomalyOnly ? { anomaly: 1 } : {}), ...(type ? { type } : {}) } })
     .then(r => r.data)

// 자연어 검색 — 질의 임베딩은 VLM 서버, 유사도는 백엔드(numpy)
export const searchLogs = (q, period = 'month', anomalyOnly = false, topK = 20) =>
  api.get('/logs/search', { params: { q, period, top_k: topK, ...(anomalyOnly ? { anomaly: 1 } : {}) } })
     .then(r => r.data)

export const getLog = (id) =>
  api.get(`/logs/${id}`).then(r => r.data)

// ── Settings ────────────────────────────────
export const getSettings = () =>
  api.get('/settings').then(r => r.data)

export const updateSettings = (payload) =>
  api.put('/settings', payload).then(r => r.data)
