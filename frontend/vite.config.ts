import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // 别名就是省事用的：别处写 import '@/api/http'，
      // 等于写 src/api/http。没它的话得一路往回数 ../../../，
      // 挪一次目录就全得跟着改
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // 5173 被占了就直接报错，不要悄悄换一个端口。
    // 换了端口我自己都不知道现在该访问哪个地址
    strictPort: true,
    proxy: {
      // 前端跑在 5173、后端跑在 8000，在浏览器眼里这就算跨域，会被拦下来。
      // 代理之后，前端只管往 /api 发请求，由 vite 这台开发服务器替你转给后端，
      // 浏览器全程只跟 5173 说话，跨域这事压根不发生。
      // 代价是：换成生产环境得由 nginx 之类的去干同一件事，
      // 所以不要把后端地址写死在前端代码里
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 把几个又大又不常改的库单独拆出去。
        // 拆开之后，以后改业务代码时它们的文件指纹不变，浏览器缓存不会失效 ——
        // 不然用户得为了几个字的改动重下一兆多。
        //
        // 说清楚：这只是拆开，总量一点没少。真要变小得让 Element Plus 按需引入
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('element-plus')) return 'vendor-element'
          // echarts 底下是 zrender 在干活，两个得搁一块 ——
          // 拆成两个文件的话它们会互相引用，反而多一次往返
          if (id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
          return 'vendor'
        },
      },
    },
  },
})
