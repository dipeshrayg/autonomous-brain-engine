import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Deployed to GitHub Project Pages at https://dipeshrayg.github.io/autonomous-brain-engine/
// so the production base must match the repo name. In dev we serve from root so
// the preview server is reachable at http://localhost:5173/.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? (process.env.VITE_BASE || '/autonomous-brain-engine/') : '/',
  server: { port: 5173, strictPort: true },
  build: { outDir: 'dist', emptyOutDir: true },
}))
