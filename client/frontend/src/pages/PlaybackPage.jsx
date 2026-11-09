import { useEffect, useState } from 'react'
import { useStore } from '../store'
import { getRecordings, getRecording, deleteRecording } from '../api'
import VideoPlayer from '../components/VideoPlayer'
import dayjs from 'dayjs'
import { anomalyLabel, fmtWindow } from '../anomaly'

export default function PlaybackPage() {
  const [selectedDate, setSelectedDate] = useState(dayjs().format('YYYY-MM-DD'))
  const [recordings, setRecordings] = useState([])
  const [selectedRec, setSelectedRec] = useState(null)   // { recording, motion_logs }
  const [loading, setLoading] = useState(false)
  const [startOffset, setStartOffset] = useState(0)      // 로그 클릭으로 넘어온 시작 지점
  const [deletingId, setDeletingId] = useState(null)

  const playbackTarget = useStore(s => s.playbackTarget)
  const setPlaybackTarget = useStore(s => s.setPlaybackTarget)

  const refreshList = () =>
    getRecordings(selectedDate)
      .then(data => setRecordings(data.recordings))
      .catch(console.error)

  // 날짜 변경 시 녹화 목록 조회
  useEffect(() => {
    setLoading(true)
    refreshList().finally(() => setLoading(false))
  }, [selectedDate])

  // 로그 페이지에서 넘어온 경우 자동 선택
  useEffect(() => {
    if (playbackTarget?.recordingId) {
      setStartOffset(playbackTarget.offsetSec ?? 0)
      loadRecording(playbackTarget.recordingId)
      setPlaybackTarget(null)
    }
  }, [])

  const loadRecording = async (id) => {
    try {
      const data = await getRecording(id)
      setSelectedRec(data)
    } catch (e) {
      console.error(e)
    }
  }

  const handleDelete = async (rec, e) => {
    e.stopPropagation()
    const label = `${fmtDateTime(rec.started_at)} 녹화`
    if (!window.confirm(`${label}를 삭제할까요?\n영상 파일과 관련 로그가 모두 삭제됩니다.`)) return
    setDeletingId(rec.id)
    try {
      await deleteRecording(rec.id)
      if (selectedRec?.recording?.id === rec.id) {
        setSelectedRec(null)
        setStartOffset(0)
      }
      await refreshList()
    } catch (err) {
      console.error(err)
      alert('삭제에 실패했습니다.')
    } finally {
      setDeletingId(null)
    }
  }

  const fmtTime = (isoStr) => dayjs(isoStr).format('HH:mm:ss')
  const fmtDateTime = (isoStr) => dayjs(isoStr).format('YYYY-MM-DD HH:mm:ss')
  const fmtDuration = (sec) => {
    if (!sec) return '-'
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m}분 ${s}초`
  }

  return (
    <div className="page playback-page">
      <div className="page-header">
        <h1>녹화 영상 재생</h1>
      </div>

      <div className="playback-layout">
        {/* 좌측: 날짜 선택 + 녹화 목록 */}
        <aside className="playback-sidebar">
          <div className="date-picker-wrap">
            <label className="date-label">날짜 선택</label>
            <input
              type="date"
              className="date-input"
              value={selectedDate}
              max={dayjs().format('YYYY-MM-DD')}
              onChange={e => {
                setSelectedDate(e.target.value)
                setSelectedRec(null)
                setStartOffset(0)
              }}
            />
          </div>

          <div className="rec-list-wrap">
            <div className="rec-list-title">
              녹화 목록
              <span className="rec-count">{recordings.length}개</span>
            </div>

            {loading ? (
              <div className="list-loading">불러오는 중...</div>
            ) : recordings.length === 0 ? (
              <div className="list-empty">이 날짜에 녹화가 없습니다.</div>
            ) : (
              <ul className="rec-list">
                {recordings.map(rec => (
                  <li
                    key={rec.id}
                    className={`rec-item ${selectedRec?.recording?.id === rec.id ? 'active' : ''}`}
                    onClick={() => { setStartOffset(0); loadRecording(rec.id) }}
                  >
                    <div className="rec-item-head">
                      <div className="rec-item-time">
                        <span className="rec-item-date">{dayjs(rec.started_at).format('YYYY-MM-DD')}</span>
                        {fmtTime(rec.started_at)}
                        {rec.ended_at && ` ~ ${fmtTime(rec.ended_at)}`}
                      </div>
                      <button
                        className="rec-del-btn"
                        title="이 녹화 삭제"
                        disabled={deletingId === rec.id}
                        onClick={e => handleDelete(rec, e)}
                      >
                        {deletingId === rec.id ? '…' : '🗑'}
                      </button>
                    </div>
                    <div className="rec-item-meta">
                      <span>{fmtDuration(rec.duration_sec)}</span>
                      {rec.file_size_mb && (
                        <span>{rec.file_size_mb} MB</span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* 우측: 영상 플레이어 */}
        <main className="playback-main">
          {selectedRec?.recording && (
            <div className="playback-title">
              {fmtDateTime(selectedRec.recording.started_at)}
              {selectedRec.recording.ended_at &&
                ` ~ ${fmtTime(selectedRec.recording.ended_at)}`}
            </div>
          )}

          <VideoPlayer
            recordingId={selectedRec?.recording?.id}
            motionLogs={selectedRec?.motion_logs ?? []}
            startOffset={startOffset}
          />

          {/* 움직임 로그 요약 */}
          {selectedRec?.motion_logs?.length > 0 && (
            <div className="motion-summary">
              <div className="motion-summary-title">
                구간 로그
                <span className="rec-count">
                  {selectedRec.motion_logs.length}건
                  {selectedRec.motion_logs.some(l => l.is_anomaly) &&
                    ` · 이상 ${selectedRec.motion_logs.filter(l => l.is_anomaly).length}건`}
                </span>
              </div>
              <ul className="motion-summary-list">
                {selectedRec.motion_logs.map(log => (
                  <li
                    key={log.id}
                    className={`motion-summary-item ${log.is_anomaly ? 'anomaly' : ''}`}
                    style={{ cursor: 'pointer' }}
                    title="클릭하면 해당 구간으로 이동"
                    onClick={() => setStartOffset((log.window_start ?? log.timestamp_offset_sec ?? 0) + 0.001)}
                  >
                    <span className="motion-time">
                      {fmtDateTime(log.detected_at)}
                      {log.window_start != null && (
                        <span className="log-window"> {fmtWindow(log.window_start)}–{fmtWindow(log.window_end)}</span>
                      )}
                    </span>
                    {log.is_anomaly
                      ? <span className="badge badge-anomaly">이상 · {anomalyLabel(log.anomaly_type)}</span>
                      : <span className="badge badge-normal">정상</span>}
                    <span className="motion-desc">
                      {log.summary || log.description || '움직임 감지됨'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
