import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import { viteStaticCopy } from 'vite-plugin-static-copy'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    viteStaticCopy({
      targets: ['Workers', 'ThirdParty', 'Assets', 'Widgets'].map((name) => ({
        src: `node_modules/cesium/Build/Cesium/${name}`,
        dest: 'cesium',
        rename: { stripBase: 4 },
      })),
    }),
  ],
  define: { CESIUM_BASE_URL: JSON.stringify('/cesium/') },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/data-files': 'http://127.0.0.1:8000',
    },
    allowedHosts:["demo.lnpbqc.online"],
  },
  preview: {
    host: '127.0.0.1',
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/data-files': 'http://127.0.0.1:8000',
    },
  },
})
