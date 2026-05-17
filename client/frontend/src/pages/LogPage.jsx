import MotionLogList from '../components/MotionLogList'

export default function LogPage() {
  return (
    <div className="page log-page">
      <div className="page-header">
        <h1>움직임 감지 로그</h1>
        <p className="page-sub">움직임이 감지된 구간을 클릭하면 해당 영상으로 이동합니다.</p>
      </div>
      <MotionLogList />
    </div>
  )
}
