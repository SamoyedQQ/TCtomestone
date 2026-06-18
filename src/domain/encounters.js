export const ENCOUNTERS = [
  { id: 1074, short: '神兵',   name: '絕 究極神兵', color: '#3b82f6', glow: 'rgba(59,130,246,0.25)' },
  { id: 1073, short: '巴哈',   name: '絕 巴哈姆特', color: '#f59e0b', glow: 'rgba(245,158,11,0.25)'  },
  { id: 1075, short: '亞歷',   name: '絕 亞歷山大', color: '#c8a46a', glow: 'rgba(200,164,106,0.25)' },
  { id: 1076, short: '龍詩',   name: '絕 龍詩戰爭', color: '#f97316', glow: 'rgba(249,115,22,0.25)'  },
  { id: 1077, short: '歐米茄', name: '絕 歐米茄',   color: '#a855f7', glow: 'rgba(168,85,247,0.25)'  },
  { id: 1079, short: '伊甸',   name: '絕 伊甸',     color: '#7dd3fc', glow: 'rgba(125,211,252,0.30)' },
]

// 玩家資料頁的副本顯示順序（新→舊）
export const PLAYER_ENCOUNTERS = [...ENCOUNTERS].sort((a, b) => b.id - a.id)

export const ENCOUNTER_MAP = Object.fromEntries(ENCOUNTERS.map(e => [e.id, e]))
export const DEFAULT_EID = 1074
