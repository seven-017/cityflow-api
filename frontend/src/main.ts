import { createPinia } from 'pinia'
import { createApp } from 'vue'

import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
// 自己的全局样式放在组件库之后引入，这样要覆盖它的时候不用加 !important
import '@/styles/main.css'

import App from '@/App.vue'
import router from '@/router'

const app = createApp(App)

// pinia 必须装在 router 前面。路由守卫里要用 store，
// 而守卫是在导航发生时执行的 —— 顺序反了会报
// "getActivePinia() was called but there was no active Pinia"
app.use(createPinia())
app.use(router)

// locale 换成中文。不换的话，分页、日期选择这些组件内置的文案全是英文，
// 界面上一半中文一半英文，看着很怪
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
