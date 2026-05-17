import { useEffect, useState } from 'react'
import { getSettings, updateSettings } from '../api'

export default function SettingsPage() {
  const [silenceSec, setSilenceSec] = useState(30)
  const [bounds, setBounds] = useState({ min: 3, max: 600 })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')

  useEffect(() => {
    getSettings()
      .then(d => {
        setSilenceSec(d.silence_sec)
        setBounds({ min: d.silence_sec_min, max: d.silence_sec_max })
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    const v = Number(silenceSec)
    if (!Number.isFinite(v) || v < bounds.min || v > bounds.max) {
      setSavedMsg(`⚠ ${bounds.min}~${bounds.max}초 사이로 입력하세요.`)
      return
    }
    setSaving(true)
    setSavedMsg('')
    try {
      const d = await updateSettings({ silence_sec: v })
      setSilenceSec(d.silence_sec)
      setSavedMsg(`✓ 저장됨 (${d.silence_sec}초)`)
    } catch (e) {
      console.error(e)
      setSavedMsg('⚠ 저장 실패')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page settings-page">
      <div className="page-header">
        <h1>설정</h1>
      </div>

      {loading ? (
        <div className="list-loading">불러오는 중...</div>
      ) : (
        <div className="settings-card">
          <div className="setting-row">
            <div className="setting-label">
              <div className="setting-name">녹화 종료 대기 시간</div>
              <div className="setting-desc">
                마지막 움직임 이후 이 시간(초) 동안 정지가 이어지면 녹화를 종료하고
                로그 1건을 남깁니다. (변경 즉시 반영)
              </div>
            </div>
            <div className="setting-control">
              <input
                type="range"
                min={bounds.min}
                max={bounds.max}
                step="1"
                value={silenceSec}
                onChange={e => setSilenceSec(Number(e.target.value))}
                className="setting-slider"
              />
              <div className="setting-number-wrap">
                <input
                  type="number"
                  min={bounds.min}
                  max={bounds.max}
                  value={silenceSec}
                  onChange={e => setSilenceSec(e.target.value)}
                  className="setting-number"
                />
                <span className="setting-unit">초</span>
              </div>
            </div>
          </div>

          <div className="setting-actions">
            <button className="btn-primary" onClick={save} disabled={saving}>
              {saving ? '저장 중...' : '저장'}
            </button>
            {savedMsg && <span className="setting-msg">{savedMsg}</span>}
          </div>
        </div>
      )}
    </div>
  )
}
