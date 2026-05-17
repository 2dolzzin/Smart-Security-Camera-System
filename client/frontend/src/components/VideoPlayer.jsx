import { useRef, useEffect, useState } from 'react'
import { getVideoUrl } from '../api'

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
          {motionLogs.map(log => (
            <div
              key={log.id}
              className="motion-marker"
              title={log.description || '움직임 감지'}
              style={{
                left: duration
                  ? `${(log.timestamp_offset_sec / duration) * 100}%`
                  : '0%',
              }}
              onClick={e => {
                e.stopPropagation()
                if (videoRef.current) videoRef.current.currentTime = log.timestamp_offset_sec
              }}
            />
          ))}
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
