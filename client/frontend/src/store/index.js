import { create } from 'zustand'

export const useStore = create((set) => ({
  // 현재 재생할 녹화 ID & 시작 오프셋 (로그 클릭 시 세팅)
  playbackTarget: null,   // { recordingId, offsetSec }
  setPlaybackTarget: (target) => set({ playbackTarget: target }),

  // 실시간 모션 상태
  motionDetected: false,
  setMotionDetected: (v) => set({ motionDetected: v }),
}))
