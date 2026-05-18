export const ROLES = [
  { id: 'Tank',   label: '坦克', color: '#60a5fa' },
  { id: 'Healer', label: '治療', color: '#34d399' },
  { id: 'Melee',  label: '近戰', color: '#f87171' },
  { id: 'Ranged', label: '遠程', color: '#fbbf24' },
  { id: 'Caster', label: '法系', color: '#c084fc' },
]

export const JOBS = {
  Paladin:     { role: 'Tank',   abbr: '騎士', color: '#a8d8ea' },
  Warrior:     { role: 'Tank',   abbr: '戰士', color: '#cf2621' },
  DarkKnight:  { role: 'Tank',   abbr: '暗騎', color: '#d126b2' },
  Gunbreaker:  { role: 'Tank',   abbr: '絕槍', color: '#796535' },
  WhiteMage:   { role: 'Healer', abbr: '白魔', color: '#e8e0cc' },
  Scholar:     { role: 'Healer', abbr: '學者', color: '#8657ff' },
  Astrologian: { role: 'Healer', abbr: '占星', color: '#ffe74a' },
  Sage:        { role: 'Healer', abbr: '賢者', color: '#80c4e0' },
  Monk:        { role: 'Melee',  abbr: '武僧', color: '#d69c00' },
  Dragoon:     { role: 'Melee',  abbr: '龍騎', color: '#4164cd' },
  Ninja:       { role: 'Melee',  abbr: '忍者', color: '#af1964' },
  Samurai:     { role: 'Melee',  abbr: '武士', color: '#e46d04' },
  Reaper:      { role: 'Melee',  abbr: '奪魂', color: '#9c5470' },
  Viper:       { role: 'Melee',  abbr: '毒蛇', color: '#108236' },
  Bard:        { role: 'Ranged', abbr: '詩人', color: '#91ba5e' },
  Machinist:   { role: 'Ranged', abbr: '機工', color: '#6ee1d6' },
  Dancer:      { role: 'Ranged', abbr: '舞者', color: '#e2b0af' },
  BlackMage:   { role: 'Caster', abbr: '黑魔', color: '#a279d0' },
  Summoner:    { role: 'Caster', abbr: '召喚', color: '#2d9b78' },
  RedMage:     { role: 'Caster', abbr: '赤魔', color: '#e87b7b' },
  Pictomancer: { role: 'Caster', abbr: '繪靈', color: '#fc78d2' },
}

export function jobsByRole(roleId) {
  return Object.entries(JOBS)
    .filter(([, j]) => j.role === roleId)
    .map(([name, j]) => ({ name, ...j }))
}

export function roleColor(roleId) {
  return ROLES.find(r => r.id === roleId)?.color ?? '#888'
}
