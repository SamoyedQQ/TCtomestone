// dev 模式直接抓遠端 GitHub Pages 資料（含 CORS: *），保證資料最新
const REMOTE = 'https://samoyedqq.github.io/TCtomestone/data'
const BASE = import.meta.env.PROD ? `${import.meta.env.BASE_URL}data` : REMOTE

export const DATA_URL = {
  meta:         `${BASE}/meta.json`,
  leaderboard:  (eid) => `${BASE}/leaderboard_${eid}.json`,
  clears:       (eid) => `${BASE}/clears_${eid}.json`,
  playersIndex: `${BASE}/players_index.json`,
}
