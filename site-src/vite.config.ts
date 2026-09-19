import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Production build for Cloudflare: hashed, immutable assets and no inline script or style, so the
// strict Content-Security-Policy in public/_headers holds. Output goes to ../site (not committed).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../site',
    emptyOutDir: true,
    target: 'es2022',
    sourcemap: false,
    cssCodeSplit: false,
    assetsInlineLimit: 0, // never inline: inlined data: URIs would need a looser CSP
    rollupOptions: {
      output: {
        // Long-lived vendor chunks: app changes do not invalidate the cached React and Motion code.
        manualChunks(id: string): string | undefined {
          if (!id.includes('node_modules')) return undefined
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react'
          if (/node_modules\/(motion|framer-motion|motion-dom|motion-utils)\//.test(id)) return 'motion'
          return undefined
        },
      },
    },
  },
})
