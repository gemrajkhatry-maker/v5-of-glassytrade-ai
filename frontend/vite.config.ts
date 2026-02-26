import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  return {
    server: {
      port: 3030,
      host: '0.0.0.0',
      proxy: {
        '/api': {
          target: 'http://localhost:9090',
          changeOrigin: true,
          ws: true,
        },
      },
    },
    plugins: [tailwindcss(), react()],
    define: {},
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      }
    }
  };
});
