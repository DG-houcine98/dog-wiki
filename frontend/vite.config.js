import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://k8s-default-lahoucin-dd80a98f00-1293314595.eu-west-2.elb.amazonaws.com',
        changeOrigin: true,
      },
    },
  },
})
