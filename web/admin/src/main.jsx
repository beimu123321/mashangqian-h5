import React from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider, App as AntdApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import 'antd/dist/reset.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <ConfigProvider
    locale={zhCN}
    theme={{ token: { colorPrimary: '#1677ff', borderRadius: 8 } }}>
    <AntdApp>
      <App />
    </AntdApp>
  </ConfigProvider>
)
