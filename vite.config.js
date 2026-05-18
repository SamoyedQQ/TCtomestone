import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { rmSync } from 'fs'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue(),
    {
      name: 'clean-assets',
      buildStart() {
        // 只清 docs/assets/，保留 docs/data/ 和 docs/img/
        try { rmSync(resolve('docs/assets'), { recursive: true, force: true }) } catch {}
      },
    },
  ],
  build: {
    outDir: 'docs',
    emptyOutDir: false, // 保留 docs/data/ 和 docs/img/
  },
})
