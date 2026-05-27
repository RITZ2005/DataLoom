import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import http from "https";
import { constants } from 'crypto';
import compression from 'vite-plugin-compression2'

const timestamp = new Date().getTime();

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [tailwindcss(),
  vue({
    template: {
      compilerOptions: {
        isCustomElement: (element) => element.startsWith('iconify-icon') || element === 'Icon'
      }
    }
  }),
  compression({ algorithms: ['gzip'] }) // Add the compression plugin here
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: "0.0.0.0",
    port: 8080,
    proxy: {
      "/api": {
        target: process.env.VITE_API_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
      "/static": {
        target: process.env.VITE_API_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
      "/server/": {
        target: "https://cs2.mkcl.org/1JFfwe3g8vHuNOtxk2BsH09pBA5",
        ws: true,
        secure: true,
        changeOrigin: true,
        agent: new http.Agent({ rejectUnauthorized: false, secureOptions: constants.SSL_OP_LEGACY_SERVER_CONNECT }),
        rewrite: (p) => p.replace(/^\/server/, ""),
      },
      "/1JFfwe3g8vHuNOtxk2BsH09pBA5/": {
        target: "https://cs2.mkcl.org/1JFfwe3g8vHuNOtxk2BsH09pBA5",
        ws: true,
        secure: true,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/1JFfwe3g8vHuNOtxk2BsH09pBA5/, ""),
      },
      "/cdnserver": {
        // target: "https://testcdncs.mkcl.org",
        target: "http://localhost:3032",
        ws: true,
        secure: false,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/cdnserver/, ""),
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        entryFileNames: `assets/[name]-[hash]-${timestamp}.js`,
        chunkFileNames: `assets/[name]-[hash]-${timestamp}.js`,
        assetFileNames: `assets/[name]-[hash]-${timestamp}.[ext]`,
        manualChunks(id) {
          if (id.includes('node_modules')) {
            return id.toString().split('node_modules/')[1].split('/')[0].toString();
          }
        }
      }
    }
  }
})
