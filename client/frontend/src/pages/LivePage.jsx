import { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'

const WS_URL = `ws://${location.host}/ws/stream`

export default function LivePage() {
  const imgRef = useRef(null)
  const wsRef = useRef(null)
  const closedRef = useRef(false)
  const reconnectTimerRef = useRef(null)
  const [connected, setConnected] = useState(false)
  const [fps, setFps] = useState(0)
  const setMotionDetected = useStore(s => s.setMotionDetected)
  const motionDetected = useStore(s => s.motionDetected)
  const fpsCountRef = useRef(0)
  const fpsTimerRef = useRef(null)

  useEffect(() => {
    // FPS 카운터
    fpsTimerRef.current = setInterval(() => {
      setFps(fpsCountRef.current)
      fpsCountRef.current = 0
    }, 1000)

    closedRef.current = false
    connect()
    return () => {
      closedRef.current = true
      clearInterval(fpsTimerRef.current)
      clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
    }
  }, [])

  const connect = () => {
    if (closedRef.current) return
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => {
      setConnected(false)
      // 언마운트되지 않았다면 3초 후 재연결
      if (!closedRef.current) {
        reconnectTimerRef.current = setTimeout(connect, 3000)
      }
    }
    ws.onerror = () => ws.close()

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)
      if (data.ping) return

      fpsCountRef.current++
      setMotionDetected(data.motion ?? false)

      if (data.frame && imgRef.current) {
        imgRef.current.src = `data:image/jpeg;base64,${data.frame}`
      }
    }
  }

  return (
    <div className="page live-page">
      <div className="page-header">
        <h1>실시간 모니터링</h1>
        <div className="live-badges">
          <span className={`badge ${connected ? 'badge-green' : 'badge-red'}`}>
            {connected ? '● LIVE' : '○ 연결 끊김'}
          </span>
          {motionDetected && (
            <span className="badge badge-red badge-pulse">⚠ 움직임 감지</span>
          )}
          <span className="badge badge-gray">{fps} FPS</span>
        </div>
      </div>

      <div className={`stream-container ${motionDetected ? 'motion-border' : ''}`}>
        <img
          ref={imgRef}
          className="stream-img"
          alt="실시간 영상"
        />
        {!connected && (
          <div className="stream-overlay">
            <span>서버에 연결 중...</span>
          </div>
        )}
      </div>

      <div className="live-info">
        <span>🔴 영상은 자동으로 저장됩니다 (30일 보관)</span>
      </div>
    </div>
  )
}
