import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { getLogs, searchLogs } from '../api'
import { useStore } from '../store'
import { anomalyLabel, fmtWindow } from '../anomaly'
import dayjs from 'dayjs'

const PERIODS = [
  { value: 'day',   label: '오늘' },
  { value: 'week',  label: '일주일' },
  { value: 'month', label: '한 달' },
]

export default function MotionLogList() {
  const [period, setPeriod] = useState('day')
  const [anomalyOnly, setAnomalyOnly] = useState(false)
  const [query, setQuery] = useState('')          // 입력창 값
  const [activeQuery, setActiveQuery] = useState('') // 실제 검색에 쓰인 값
  const [logs, setLogs] = useState([])
  const [anomalyTotal, setAnomalyTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const setPlaybackTarget = useStore(s => s.setPlaybackTarget)
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true); setError('')
    const req = activeQuery
      ? searchLogs(activeQuery, period, anomalyOnly)
      : getLogs(period, anomalyOnly)
    req
      .then(data => {
        setLogs(data.logs)
        setAnomalyTotal(data.anomaly_total ?? data.logs.filter(l => l.is_anomaly).length)
      })
      .catch(e => {
        console.error(e)
        setError(e?.response?.data?.detail || '불러오기 실패')
        setLogs([])
      })
      .finally(() => setLoading(false))
  }, [period, anomalyOnly, activeQuery])

  // 이상 로그 상단 고정(검색 결과는 유사도순 그대로)
  const ordered = useMemo(() => {
    if (activeQuery) return logs
    const an = logs.filter(l => l.is_anomaly)
    const no = logs.filter(l => !l.is_anomaly)
    return [...an, ...no]
  }, [logs, activeQuery])

  const handleClick = (log) => {
    setPlaybackTarget({
      recordingId: log.recording_id,
      offsetSec: log.window_start ?? log.timestamp_offset_sec ?? 0,
    })
    navigate('/playback')
  }

  const submitSearch = (e) => {
    e.preventDefault()
    setActiveQuery(query.trim())
  }

  const formatDate = (isoStr) => {
    const d = dayjs(isoStr)
    return `${d.month() + 1}월 ${d.date()}일 ${d.format('HH:mm:ss')}`
  }

  return (
    <div className="log-list-wrap">
      {/* 자연어 검색 */}
      <form className="log-search" onSubmit={submitSearch}>
        <input
          className="log-search-input"
          placeholder="자연어로 검색 — 예: 편의점에서 물건을 가져감, 사람이 쓰러짐"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <button type="submit" className="log-search-btn">검색</button>
        {activeQuery && (
          <button type="button" className="log-search-clear"
                  onClick={() => { setQuery(''); setActiveQuery('') }}>
            지우기
          </button>
        )}
      </form>

      {/* 기간 필터 + 이상만 보기 */}
      <div className="period-filter">
        {PERIODS.map(p => (
          <button
            key={p.value}
            className={`period-btn ${period === p.value ? 'active' : ''}`}
            onClick={() => setPeriod(p.value)}
          >
            {p.label}
          </button>
        ))}
        <button
          className={`period-btn anomaly-toggle ${anomalyOnly ? 'active' : ''}`}
          onClick={() => setAnomalyOnly(v => !v)}
          title="이상으로 판정된 로그만 표시"
        >
          이상만 보기{anomalyTotal > 0 && !anomalyOnly ? ` (${anomalyTotal})` : ''}
        </button>
      </div>

      {activeQuery && !loading && (
        <div className="log-search-info">"{activeQuery}" 검색 결과 {logs.length}건 (유사도순)</div>
      )}

      {/* 로그 목록 */}
      {loading ? (
        <div className="log-loading">불러오는 중...</div>
      ) : error ? (
        <div className="log-empty">{error}</div>
      ) : ordered.length === 0 ? (
        <div className="log-empty">
          {activeQuery ? '검색 결과가 없습니다.' : anomalyOnly ? '이 기간에는 이상 로그가 없습니다.' : '이 기간에는 감지된 움직임이 없습니다.'}
        </div>
      ) : (
        <ul className="log-list">
          {ordered.map(log => (
            <li
              key={log.id}
              className={`log-item ${log.is_anomaly ? 'anomaly' : ''}`}
              onClick={() => handleClick(log)}
            >
              <span className="log-time">
                {formatDate(log.detected_at)}
                {log.window_start != null && (
                  <span className="log-window">+{fmtWindow(log.window_start)}</span>
                )}
              </span>
              <span className="log-body">
                <span className="log-badges">
                  {log.is_anomaly ? (
                    <span className="badge badge-anomaly">이상 · {anomalyLabel(log.anomaly_type)}</span>
                  ) : (
                    <span className="badge badge-normal">정상</span>
                  )}
                  {log.scene && <span className="badge badge-scene">{log.scene}</span>}
                  {log.score != null && <span className="badge badge-score">{(log.score * 100).toFixed(0)}%</span>}
                </span>
                <span className="log-desc">{log.summary || log.description || '움직임 감지됨'}</span>
                {log.action && log.action !== log.summary && (
                  <span className="log-action">{log.action}</span>
                )}
              </span>
              <span className="log-arrow">›</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
