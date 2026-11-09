import { useRef, useEffect, useState } from 'react'
import { getVideoUrl } from '../api'
import { anomalyLabel } from '../anomaly'

export default function VideoPlayer({ recordingId, motionLogs = [], startOffset = 0 }) {
  const videoRef = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [speed, setSpeed] = useState(1)

  const src = recordingId ? getVideoUrl(recordingId) : null

  // 시작 오프셋 적용 (로그 클릭으로 넘어온 경우)
  useEffect(() => {
    if (videoRef.current && startOffset > 0) {
      videoRef.current.currentTime = startOffset
    }
  }, [recordingId, startOffset])

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = speed
    }
  }, [speed])

  const togglePlay = () => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) { v.play(); setPlaying(true) }
    else { v.pause(); setPlaying(false) }
  }

  const seek = (e) => {
    const bar = e.currentTarget
    const ratio = (e.clientX - bar.getBoundingClientRect().left) / bar.offsetWidth
    if (videoRef.current) videoRef.current.currentTime = ratio * duration
  }

  const fmtTime = (s) => {
    const m = Math.floor(s / 60).toString().padStart(2, '0')
    const sec = Math.floor(s % 60).toString().padStart(2, '0')
    return `${m}:${sec}`
  }

  if (!src) return (
    <div className="player-empty">날짜와 시간을 선택하여 영상을 재생하세요.</div>
  )

  return (
    <div className="video-player">
      <div className="video-wrap">
        <video
          ref={videoRef}
          src={src}
          className="video-el"
          onTimeUpdate={e => setCurrentTime(e.target.currentTime)}
          onLoadedMetadata={e => {
            setDuration(e.target.duration)
            if (startOffset > 0) e.target.currentTime = startOffset
          }}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
      </div>

      {/* 타임라인 */}
      <div className="timeline-wrap">
        <div className="timeline-bar" onClick={seek}>
          {/* 진행 바 */}
          <div
            className="timeline-progress"
            style={{ width: duration ? `${(currentTime / duration) * 100}%` : '0%' }}
          />
          {/* 움직임 마커 */}
          {motionLogs.map(log => {
            const start = log.window_start ?? log.timestamp_offset_sec ?? 0
            const end = log.window_end
            const label = (log.is_anomaly ? `[이상 · ${anomalyLabel(log.anomaly_type)}] ` : '[정상] ')
              + (log.summary || log.description || '움직임 감지')
            return (
              <div
                key={log.id}
                className={`motion-marker ${log.is_anomaly ? 'anomaly' : 'normal'}`}
                title={label}
                style={{
                  left: duration ? `${(start / duration) * 100}%` : '0%',
                  // 창 구간이 있으면 마커를 구간 길이만큼 늘림
                  ...(end != null && duration
                    ? { width: `${Math.max(1.5, ((end - start) / duration) * 100)}%`, borderRadius: 4, transform: 'translateY(-50%)' }
                    : {}),
                }}
                onClick={e => {
                  e.stopPropagation()
                  if (videoRef.current) videoRef.current.currentTime = start
                }}
              />
            )
          })}
        </div>
        <div className="timeline-time">
          <span>{fmtTime(currentTime)}</span>
          <span>{fmtTime(duration)}</span>
        </div>
      </div>

      {/* 컨트롤 */}
      <div className="player-controls">
        <button className="ctrl-btn" onClick={togglePlay}>
          {playing ? '⏸' : '▶'}
        </button>
        <div className="speed-group">
          {[0.5, 1, 2, 4].map(s => (
            <button
              key={s}
              className={`speed-btn ${speed === s ? 'active' : ''}`}
              onClick={() => setSpeed(s)}
            >
              {s}×
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
