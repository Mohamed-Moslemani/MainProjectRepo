import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Path aliases for the monorepo-style src layout:
//   src/apps/<role>/   role-specific pages + components
//   src/shared/        cross-role infrastructure (auth, api, ui)
// Aliasing means moving a file across folders later doesn't churn
// every consumer's import path.
export default defineConfig({
  plugins: [react()],
  appType: 'spa',
  resolve: {
    alias: {
      '@shared': path.resolve(__dirname, 'src/shared'),
      '@citizen': path.resolve(__dirname, 'src/apps/citizen'),
      '@clerk': path.resolve(__dirname, 'src/apps/clerk'),
      '@mukhtar': path.resolve(__dirname, 'src/apps/mukhtar'),
    },
  },
})
