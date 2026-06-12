import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In Docker, the API is reachable at the 'api' service name; in local dev,
// override with VITE_API_BASE / VITE_WS_BASE. Defaults assume localhost.
export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5173 },
})
