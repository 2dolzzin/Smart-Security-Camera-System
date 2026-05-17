import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getLogs } from '../api'
import { useStore } from '../store'
import dayjs from 'dayjs'

const PERIODS = [
  { value: 'day',   label: '오늘' },
  { value: 'week',  label: '일주일' },
  { value: 'month', label: '한 달' },
]

export default function MotionLogList() {
  const [period, setPeriod] = useState('day')
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const setPlaybackTarget = useStore(s => s.setPlaybackTarget)
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true)
    getLogs(period)
      .then(data => setLogs(data.logs))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [period])

  const handleClick = (log) => {
    setPlaybackTarget({
      recordingId: log.recording_id,
      offsetSec: log.timestamp_offset_sec ?? 0,
    })
    navigate('/playback')
  }

  const formatDate = (isoStr) => {
    const d = dayjs(isoStr)
    return `${d.month() + 1}월 ${d.date()}일 ${d.format('HH:mm')}`
  }

  return (
    <div className="log-list-wrap">
      {/* 기간 필터 */}
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
      </div>

      {/* 로그 목록 */}
      {loading ? (
        <div className="log-loading">불러오는 중...</div>
      ) : logs.length === 0 ? (
        <div className="log-empty">이 기간에는 감지된 움직임이 없습니다.</div>
      ) : (
        <ul className="log-list">
          {logs.map(log => (
            <li
              key={log.id}
              className="log-item"
              onClick={() => handleClick(log)}
            >
              <span className="log-time">{formatDate(log.detected_at)}</span>
              <span className="log-desc">
                {log.description || '움직임 감지됨'}
              </span>
              <span className="log-arrow">›</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
