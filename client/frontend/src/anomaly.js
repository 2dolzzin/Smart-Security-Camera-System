// 이상 유형(영문 열거형, UCF-Crime 폴더명) → 한국어 표시명. 열거형 값 자체는 영어로 저장·전송된다.
export const ANOMALY_LABELS = {
  Abuse: '학대', Arrest: '체포', Arson: '방화', Assault: '폭행', Burglary: '침입절도',
  Explosion: '폭발', Fighting: '싸움', RoadAccidents: '교통사고', Robbery: '강도',
  Shooting: '총격', Shoplifting: '상점절도', Stealing: '절도', Vandalism: '기물파손',
}

export const anomalyLabel = (type) => ANOMALY_LABELS[type] || (type && type !== 'None' ? type : '이상')

export const fmtWindow = (s) => {
  if (s == null) return ''
  const m = Math.floor(s / 60), sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}
