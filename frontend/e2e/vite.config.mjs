import config from '../vite.config.js'

// Test-only port: never reuse an existing developer API.
export default {
  ...config,
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:5052' },
  },
}
