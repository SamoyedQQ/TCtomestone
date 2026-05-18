// 永遠使用遠端 GitHub Pages 資料（含 CORS: *），保證資料最新
// prod 部署後改成相對路徑 /data 即可
const REMOTE = 'https://samoyedqq.github.io/TCtomestone/data'
const BASE = import.meta.env.PROD ? '/data' : REMOTE

export const DATA_URL = {
  meta:         `${BASE}/meta.json`,
  leaderboard:  (eid) => `${BASE}/leaderboard_${eid}.json`,
  clears:       (eid) => `${BASE}/clears_${eid}.json`,
  playersIndex: `${BASE}/players_index.json`,
}
