import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        // Local dev proxies /api/* through to the live cluster (your IP must be in the
        // ingress allowlist at k8s/ingress.yaml). Use --insecure-https if the cert
        // doesn't match.
        target: 'https://mcse-dogwiki.com',
        changeOrigin: true,
        secure: true,
      },
    },
  },
})
