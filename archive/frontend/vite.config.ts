import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ mode }) => {
  const repoRoot = path.resolve(__dirname, '..');
  // Merge repo + frontend env so PORT from backend/.env or root .env matches the proxy.
  const envAll = { ...loadEnv(mode, repoRoot, ''), ...loadEnv(mode, __dirname, '') };
  const backendPort = envAll.VITE_BACKEND_PORT || envAll.PORT || '9090';
  const proxyTarget =
    envAll.VITE_PROXY_TARGET?.replace(/\/$/, '') ||
    `http://127.0.0.1:${backendPort}`;

  const apiProxy = {
    target: proxyTarget,
    changeOrigin: true,
    ws: true,
  };

  return {
    server: {
      port: 5190,
      host: '0.0.0.0',
      proxy: {
        '/api': apiProxy,
      },
    },
    preview: {
      port: 5190,
      host: '0.0.0.0',
      proxy: {
        '/api': apiProxy,
      },
    },
    plugins: [tailwindcss(), react()],
    define: {},
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      }
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./tests/setup.ts'],
      include: ['tests/**/*.test.{ts,tsx}'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'json', 'html'],
      },
    },
  };
});
