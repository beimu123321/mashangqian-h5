import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  Layout, Grid, Card, Button, Modal, Image, Tabs, Table, Tag, Switch, Input, InputNumber, Form,
  message, Drawer, List, Empty, Spin, Avatar, Statistic, Space, Typography,
  Popconfirm, Select, Badge, Tooltip, Divider, Alert, Radio,
} from 'antd'
import {
  QrcodeOutlined, PlusOutlined, ReloadOutlined, SettingOutlined, LogoutOutlined,
  MessageOutlined, AppstoreOutlined, UserOutlined, CheckCircleTwoTone,
  ExclamationCircleTwoTone, CloseCircleTwoTone,   ClockCircleOutlined,
  CloseOutlined, NotificationOutlined, MailOutlined, ReadOutlined, ThunderboltOutlined,
  InfoCircleOutlined, CheckCircleOutlined, ExclamationCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const { Header, Content, Sider } = Layout
const { Title, Text } = Typography

const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  let j = {}
  try { j = await res.json() } catch (e) {}
  if (j && j.ok === false) throw new Error(j.msg || '请求失败')
  if (!res.ok) throw new Error(j.msg || `HTTP ${res.status}`)
  return j
}

const APP_VERSION = 'v1.0.0'

const signTypeLabel = (o) => {
  const m = { 0: '普通/拍照', 2: '二维码', 3: '手势', 4: '位置', 5: '签到码' }
  return m[o] || '普通'
}

export default function App() {
  const [user, setUser] = useState(null)        // {username, role}
  const [bootstrap, setBootstrap] = useState(true)
  const [view, setView] = useState('profile')  // profile | accounts

  const [accounts, setAccounts] = useState([])
  const [loadingAccts, setLoadingAccts] = useState(false)

  // QR modal
  const [qrOpen, setQrOpen] = useState(false)
  const [qrData, setQrData] = useState(null)     // {qr_id, qr}
  const [qrStatus, setQrStatus] = useState('')
  const pollRef = useRef(null)
  const qrIdRef = useRef(null)                     // 当前二维码会话 id（避免轮询闭包拿到旧的 qrData）

  // drawer
  const [drawer, setDrawer] = useState(null)      // {acctId, tab}
  const [detail, setDetail] = useState(null)
  const [records, setRecords] = useState([])
  const [coursesRefreshing, setCoursesRefreshing] = useState(false)
  const formRef = useRef(null)

  // tickets
  const [tickets, setTickets] = useState([])
  const [ticketOpen, setTicketOpen] = useState(false)
  const [ticketDetail, setTicketDetail] = useState(null)
  const [ticketReply, setTicketReply] = useState('')

  // announcements (banner, public)
  const [announcements, setAnnouncements] = useState([])
  const [dismissed, setDismissed] = useState(() => {
    try { return JSON.parse(localStorage.getItem('dismissed_announcements') || '[]') } catch { return [] }
  })
  const dismissAnn = (id) => {
    const nd = [...dismissed, id]
    setDismissed(nd)
    localStorage.setItem('dismissed_announcements', JSON.stringify(nd))
  }
  const loadAnnouncements = useCallback(async () => {
    try {
      const j = await api('/api/announcements')
      setAnnouncements(j.announcements || [])
    } catch (e) {}
  }, [])
  useEffect(() => {
    loadAnnouncements()
    const t = setInterval(loadAnnouncements, 60000)
    return () => clearInterval(t)
  }, [loadAnnouncements])

  // 消息中心未读数（登录后每 30s 轮询）
  const [msgUnread, setMsgUnread] = useState(0)
  const loadMsgUnread = useCallback(async () => {
    if (!user) return
    try {
      const j = await api('/api/messages/unread-count')
      setMsgUnread(j.unread || 0)
    } catch (e) {}
  }, [user])
  useEffect(() => {
    if (!user) return
    loadMsgUnread()
    const t = setInterval(loadMsgUnread, 30000)
    return () => clearInterval(t)
  }, [user, loadMsgUnread])

  const [msg, ctx] = message.useMessage()
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md

  // ---- bootstrap ----
  const loadMe = useCallback(async () => {
    try {
      const j = await api('/api/auth/me')
      if (j.logged_in) setUser(j.user)
      else setUser(false)
    } catch (e) {
      setUser(false)
    } finally {
      setBootstrap(false)
    }
  }, [])

  useEffect(() => { loadMe() }, [])

  // ---- accounts polling ----
  const loadAccounts = useCallback(async () => {
    try {
      const j = await api('/api/accounts')
      setAccounts(j.accounts || [])
    } catch (e) {}
  }, [])

  useEffect(() => {
    if (!user) return
    loadAccounts()
    setLoadingAccts(false)
    const t = setInterval(loadAccounts, 2500)
    return () => clearInterval(t)
  }, [user, loadAccounts])

  // ---- login/logout ----
  const doLogout = async () => {
    await api('/api/auth/logout', { method: 'POST' })
    setUser(false)
    setAccounts([])
    msg.success('已退出登录')
  }

  // ---- QR flow ----
  const startQr = useCallback(async () => {
    try {
      const j = await api('/api/qr/start', { method: 'POST' })
      setQrData({ qr_id: j.qr_id, qr: j.qr })
      qrIdRef.current = j.qr_id
      setQrStatus('等待扫码…')
    } catch (e) {
      setQrStatus('获取二维码失败: ' + e.message)
    }
  }, [])

  const openQr = async () => {
    setQrOpen(true)
    setQrData(null)
    setQrStatus('生成中…')
    await startQr()
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      const qid = qrIdRef.current
      if (!qid) return
      try {
        const j = await api('/api/qr/poll?qr_id=' + qid)
        const s = j.status
        if (s === 'confirmed') {
          clearInterval(pollRef.current)
          qrIdRef.current = null
          setQrStatus('登录成功！')
          msg.success('学习通账号已添加')
          setQrOpen(false)
          loadAccounts()
        } else if (s === 'scanned') {
          setQrStatus('已扫描，请在手机上确认登录…')
        } else if (s === 'expired' || s === 'canceled' || s === 'failed') {
          setQrStatus('二维码失效，正在刷新…')
          await startQr()
        }
      } catch (e) {}
    }, 2000)
  }

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  // ---- account actions ----
  const toggleMonitor = async (a, on) => {
    try {
      await api(`/api/accounts/${a.acct_id}/monitor`, { method: 'POST', body: JSON.stringify({ on }) })
      loadAccounts()
    } catch (e) { msg.error(e.message) }
  }

  const openDetail = async (a, tab = 'config') => {
    setDrawer({ acct_id: a.acct_id, tab })
    try {
      const j = await api('/api/accounts/' + a.acct_id)
      setDetail(j.account)
      const r = await api('/api/accounts/' + a.acct_id + '/records')
      setRecords(r.records || [])
    } catch (e) { msg.error(e.message) }
  }

  const saveConfig = async (values) => {
    try {
      await api(`/api/accounts/${drawer.acct_id}/config`, {
        method: 'POST', body: JSON.stringify({
          interval: values.interval, serverchan_key: values.serverchan_key,
          enabled_courses: values.enabled_courses || [],
          loc_enabled: !!values.loc_enabled,
          loc_lat: (values.loc_lat || '').toString().trim(),
          loc_lng: (values.loc_lng || '').toString().trim(),
          loc_addr: (values.loc_addr || '').toString().trim(),
        }),
      })
      msg.success('配置已保存')
      openDetail({ acct_id: drawer.acct_id }, 'config')
    } catch (e) { msg.error(e.message) }
  }

  const refreshCourses = async () => {
    if (!drawer) return
    setCoursesRefreshing(true)
    try {
      const j = await api(`/api/accounts/${drawer.acct_id}/courses/refresh`, { method: 'POST' })
      const list = j.courses || []
      setDetail(d => (d ? { ...d, courses: list } : d))
      msg.success(`课程列表已刷新，共 ${list.length} 门`)
    } catch (e) { msg.error(e.message) }
    finally { setCoursesRefreshing(false) }
  }

  const removeAccount = async (a) => {
    try {
      await api('/api/accounts/' + a.acct_id, { method: 'DELETE' })
      msg.success('已移除账号')
      loadAccounts()
    } catch (e) { msg.error(e.message) }
  }

  const logoutAccount = async (a) => {
    try {
      await api('/api/accounts/' + a.acct_id + '/logout', { method: 'POST' })
      msg.success('账号已退出')
      loadAccounts()
    } catch (e) { msg.error(e.message) }
  }

  // 手动检测：先验学习通登录态，再立即扫描一轮全部课程
  const runAccountCheck = async (a) => {
    const j = await api(`/api/accounts/${a.acct_id}/check`, { method: 'POST' })
    loadAccounts()
    if (drawer && drawer.acct_id === a.acct_id && drawer.tab === 'records') {
      try {
        const r = await api(`/api/accounts/${a.acct_id}/records`)
        setRecords(r.records || [])
      } catch (e) {}
    }
    return j
  }

  // ---- tickets ----
  const loadTickets = useCallback(async () => {
    try {
      const j = await api('/api/tickets')
      setTickets(j.tickets || [])
    } catch (e) {}
  }, [])

  useEffect(() => {
    if (user && view === 'profile') loadTickets()
  }, [user, view, loadTickets])

  const submitTicket = async (v) => {
    try {
      await api('/api/tickets', { method: 'POST', body: JSON.stringify(v) })
      msg.success('工单已提交')
      setTicketOpen(false)
      loadTickets()
    } catch (e) { msg.error(e.message) }
  }

  const openTicket = async (t) => {
    try {
      const j = await api('/api/tickets/' + t.id)
      setTicketDetail(j.ticket)
      setTicketReply('')
    } catch (e) { msg.error(e.message) }
  }

  const sendTicketReply = async () => {
    if (!ticketReply.trim()) return
    try {
      await api(`/api/tickets/${ticketDetail.id}/reply`, {
        method: 'POST', body: JSON.stringify({ message: ticketReply }),
      })
      openTicket(ticketDetail)
      loadTickets()
      setTicketReply('')
    } catch (e) { msg.error(e.message) }
  }

  if (bootstrap) return <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin size="large" /></div>

  // ===== 未登录：登录/注册 =====
  if (!user) return (
    <>
      <AuthPage onLogin={(u) => setUser(u)} onRegistered={(u) => setUser(u)} msgCtx={ctx} />
      <AnnouncementPopup announcements={announcements} dismissed={dismissed} onDismiss={dismissAnn} />
    </>
  )

  // ===== 已登录主界面 =====
  const menuItems = [
    { key: 'profile', icon: <UserOutlined />, label: '个人主页' },
    { key: 'accounts', icon: <AppstoreOutlined />, label: '我的账号' },
    { key: 'messages', icon: <NotificationOutlined />, label: '消息中心' },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {ctx}
      <AnnouncementPopup announcements={announcements} dismissed={dismissed} onDismiss={dismissAnn} />
      {!isMobile && (
      <Sider theme="light" width={200} style={{ borderRight: '1px solid #f0f0f0' }}>
        <div style={{ padding: '20px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <img src="/static/logo.png" alt="马上签" style={{ width: 34, height: 34, objectFit: 'contain' }} />
          <span style={{ fontWeight: 700, color: '#1677ff', fontSize: 17 }}>马上签</span>
        </div>
        <Tabs activeKey={view} onChange={setView} items={menuItems.map(m => ({ key: m.key, label: (
          <span><span style={{ color: '#1677ff' }}>{m.icon}</span> {m.label}{m.key === 'messages' && msgUnread > 0 ? <Badge count={msgUnread} style={{ marginLeft: 6, backgroundColor: '#ff4d4f', boxShadow: 'none' }} /> : null}</span>
        ) }))} tabPosition="left" style={{ paddingLeft: 12 }} />
        <div style={{ position: 'absolute', bottom: 16, left: 16, right: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>当前用户：{user.username}</Text>
            <Button block icon={<ReadOutlined />} href="/help" target="_blank">使用教程</Button>
            <Button block icon={<LogoutOutlined />} onClick={doLogout}>退出登录</Button>
          </Space>
        </div>
      </Sider>
      )}
      <Layout>
        <Header style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: isMobile ? '0 12px' : '0 24px' }}>
          {isMobile
            ? <Space><img src="/static/logo.png" alt="马上签" style={{ width: 26, height: 26, objectFit: 'contain' }} /><span style={{ fontWeight: 700, color: '#1677ff', fontSize: 18 }}>马上签</span></Space>
            : <Title level={4} style={{ margin: 0 }}>{view === 'accounts' ? '我的学习通账号' : view === 'messages' ? '消息中心' : '个人主页'}</Title>}
          <Space>
            {isMobile && <Button type="text" icon={<LogoutOutlined />} onClick={doLogout} />}
          </Space>
        </Header>
        <Content style={{ padding: isMobile ? 12 : 24, paddingBottom: isMobile ? 76 : 24 }}>
          {view === 'messages' ? (
            <MessagesView onChanged={loadMsgUnread} isMobile={isMobile} />
          ) : view === 'accounts' ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, gap: 8, flexWrap: 'wrap' }}>
                <Text type="secondary">共 {accounts.length} 个学习通账号</Text>
                <Button type="primary" icon={<PlusOutlined />} onClick={openQr}>添加学习通账号</Button>
              </div>
              {loadingAccts && accounts.length === 0 ? <Spin />
                : accounts.length === 0 ? (
                  <Empty description="还没有学习通账号" style={{ marginTop: 60 }}>
                    <Button type="primary" icon={<PlusOutlined />} onClick={openQr}>添加学习通账号</Button>
                  </Empty>
                ) : (
                  <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill,minmax(320px,1fr))', gap: isMobile ? 12 : 16 }}>
                    {accounts.map(a => (
                      <AccountCard key={a.acct_id} a={a} onToggle={toggleMonitor}
                        onOpen={openDetail} onRemove={removeAccount} onLogout={logoutAccount}
                        onCheck={runAccountCheck} />
                    ))}
                  </div>
                )}
            </>
          ) : (
            <ProfileView user={user} accounts={accounts} tickets={tickets}
              onOpenTicket={openTicket} onNewTicket={() => setTicketOpen(true)}
              onUserUpdate={setUser} isMobile={isMobile} />
          )}
        </Content>
      </Layout>

      {isMobile && (
        <div style={{ position: 'fixed', bottom: 0, left: 0, right: 0, display: 'flex', background: '#fff', borderTop: '1px solid #f0f0f0', zIndex: 20, paddingBottom: 'env(safe-area-inset-bottom)' }}>
          {menuItems.map(m => (
            <div key={m.key} onClick={() => setView(m.key)} style={{ flex: 1, textAlign: 'center', padding: '10px 0', cursor: 'pointer', color: view === m.key ? '#1677ff' : '#888', fontSize: 12, position: 'relative' }}>
              <div style={{ fontSize: 18, position: 'relative', display: 'inline-block' }}>
                {m.icon}
                {m.key === 'messages' && msgUnread > 0 && (
                  <span style={{ position: 'absolute', top: -2, right: -8, minWidth: 14, height: 14, borderRadius: 7, background: '#ff4d4f', color: '#fff', fontSize: 10, lineHeight: '14px', padding: '0 3px', transform: 'scale(.9)' }}>{msgUnread > 99 ? '99+' : msgUnread}</span>
                )}
              </div>
              <div>{m.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* QR 弹窗 */}
      <Modal title="扫码添加学习通账号" open={qrOpen} onCancel={() => { setQrOpen(false); qrIdRef.current = null; if (pollRef.current) clearInterval(pollRef.current) }} footer={null} centered width={isMobile ? '92vw' : 520}>
        <div style={{ textAlign: 'center', padding: 16 }}>
          {qrData ? (
            <>
              <Image src={`data:image/png;base64,${qrData.qr}`} width={isMobile ? 200 : 240} height={isMobile ? 200 : 240} preview={false} />
              <div style={{ marginTop: 12 }}><Text>{qrStatus}</Text></div>
              <Button style={{ marginTop: 12 }} onClick={startQr}>刷新二维码</Button>
            </>
          ) : <Spin tip={qrStatus} />}
          <Alert type="info" showIcon style={{ marginTop: 16, textAlign: 'left' }}
            message="用学习通 App 扫描二维码登录。绑定后普通、手势、签到码、位置签到自动完成，二维码与拍照签到将提醒你处理。" />
        </div>
      </Modal>

      {/* 账号详情抽屉 */}
      <Drawer title={detail ? `${detail.name || detail.acct_id} 的详情` : '详情'} width={isMobile ? '92vw' : 520} open={!!drawer} onClose={() => setDrawer(null)}>
        {detail && (
          <Tabs defaultActiveKey="config" items={[
            { key: 'config', label: '配置', children: <ConfigTab detail={detail} onSave={saveConfig} onRefreshCourses={refreshCourses} refreshing={coursesRefreshing} /> },
            { key: 'records', label: `签到记录 (${records.length})`, children: <RecordsTab records={records} /> },
          ]} />
        )}
      </Drawer>

      {/* 新建工单 */}
      <Modal title="提交工单" open={ticketOpen} onCancel={() => setTicketOpen(false)} onOk={() => formRef.current?.submit()} okText="提交" destroyOnClose>
        <TicketForm formRef={formRef} onSubmit={submitTicket} />
      </Modal>

      {/* 工单详情 */}
      <Drawer title={ticketDetail ? `工单 #${ticketDetail.id} ${ticketDetail.subject}` : ''} width={isMobile ? '92vw' : 560} open={!!ticketDetail} onClose={() => setTicketDetail(null)}>
        {ticketDetail && (
          <TicketDetail t={ticketDetail} reply={ticketReply} setReply={setTicketReply} onSend={sendTicketReply} />
        )}
      </Drawer>
    </Layout>
  )
}

// ---------- 登录/注册 ----------
// ===== 公告弹窗：自动弹出，逐条展示，点「我知道了」关闭并记住 =====
const ANN_TYPE_MAP = {
  info: { icon: <InfoCircleOutlined />, color: '#1677ff', tag: 'blue', label: '通知' },
  success: { icon: <CheckCircleOutlined />, color: '#52c41a', tag: 'green', label: '公告' },
  warning: { icon: <ExclamationCircleOutlined />, color: '#faad14', tag: 'orange', label: '提示' },
  error: { icon: <CloseCircleOutlined />, color: '#ff4d4f', tag: 'red', label: '重要' },
}

function AnnouncementPopup({ announcements, dismissed, onDismiss }) {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const [curId, setCurId] = useState(null)
  const pending = (announcements || []).filter(a => !dismissed.includes(a.id))
  const current = pending.find(a => a.id === curId) || pending[0] || null
  const close = () => {
    if (!current) return
    onDismiss(current.id)
    setCurId(null)
  }
  if (!current) return null
  const t = ANN_TYPE_MAP[current.type] || ANN_TYPE_MAP.info
  return (
    <Modal
      open
      centered
      width={isMobile ? '86vw' : 520}
      closable={false}
      maskClosable={false}
      onCancel={close}
      footer={
        <div style={{ textAlign: 'center' }}>
          <Button type="primary" size="large" style={{ minWidth: 180 }} onClick={close}>我知道了</Button>
        </div>
      }
    >
      <div style={{ textAlign: 'center', paddingTop: 4 }}>
        <div style={{ fontSize: 46, color: t.color, lineHeight: 1 }}>{t.icon}</div>
        <div style={{ margin: '10px 0 2px' }}><Tag color={t.tag}>{t.label}</Tag></div>
        <Title level={4} style={{ marginBottom: 14 }}>{current.title}</Title>
      </div>
      <div style={{
        whiteSpace: 'pre-wrap', textAlign: 'left', background: '#fafafa',
        border: '1px solid #f0f0f0', borderRadius: 8, padding: '14px 16px',
        lineHeight: 1.9, color: '#4a4f59', maxHeight: '46vh', overflow: 'auto', fontSize: 14,
      }}>{current.content}</div>
    </Modal>
  )
}

// ===== 消息中心 =====
const MSG_TYPE_MAP = {
  announcement: { label: '公告', icon: <NotificationOutlined />, color: '#1677ff', tag: 'blue' },
  sign: { label: '签到', icon: <CheckCircleOutlined />, color: '#52c41a', tag: 'green' },
  ticket: { label: '工单', icon: <MessageOutlined />, color: '#fa8c16', tag: 'orange' },
  system: { label: '系统', icon: <InfoCircleOutlined />, color: '#722ed1', tag: 'purple' },
}

function msgIconOf(m) {
  if (m.type === 'sign') {
    if (m.title.indexOf('失败') >= 0) return { icon: <CloseCircleOutlined />, color: '#ff4d4f' }
    if (m.title.indexOf('需手动') >= 0) return { icon: <ExclamationCircleOutlined />, color: '#faad14' }
    return { icon: <CheckCircleOutlined />, color: '#52c41a' }
  }
  const t = MSG_TYPE_MAP[m.type] || MSG_TYPE_MAP.system
  return { icon: t.icon, color: t.color }
}

function MessagesView({ onChanged, isMobile }) {
  const [items, setItems] = useState([])
  const [unread, setUnread] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')  // all / unread / announcement / sign / ticket / system

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const q = filter === 'all' ? '' : filter === 'unread' ? '?unread=1' : `?type=${filter}`
      const j = await api('/api/messages' + q)
      setItems(j.messages || [])
      setUnread(j.unread || 0)
    } catch (e) {} finally { setLoading(false) }
  }, [filter])

  useEffect(() => { load() }, [load])

  const markRead = async (m) => {
    if (m.read) return
    try {
      await api(`/api/messages/${m.id}/read`, { method: 'POST' })
      setItems(prev => prev.map(x => x.id === m.id ? { ...x, read: true } : x))
      setUnread(u => Math.max(0, u - 1))
      onChanged && onChanged()
    } catch (e) {}
  }

  const readAll = async () => {
    try {
      await api('/api/messages/read-all', { method: 'POST' })
      setItems(prev => prev.map(x => ({ ...x, read: true })))
      setUnread(0)
      onChanged && onChanged()
      message.success('已全部标为已读')
    } catch (e) {}
  }

  const clearRead = async () => {
    try {
      await api('/api/messages/read/clear', { method: 'POST' })
      load()
      onChanged && onChanged()
      message.success('已清空已读消息')
    } catch (e) {}
  }

  const filters = [
    { key: 'all', label: '全部' },
    { key: 'unread', label: unread ? `未读 (${unread})` : '未读' },
    { key: 'announcement', label: '公告' },
    { key: 'sign', label: '签到' },
    { key: 'ticket', label: '工单' },
    { key: 'system', label: '系统' },
  ]

  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, gap: 8, flexWrap: 'wrap' }}>
        <Radio.Group value={filter} onChange={e => setFilter(e.target.value)} optionType="button" buttonStyle="solid" size="small">
          {filters.map(f => <Radio.Button key={f.key} value={f.key}>{f.label}</Radio.Button>)}
        </Radio.Group>
        <Space>
          <Button size="small" onClick={readAll} disabled={unread === 0}>全部已读</Button>
          <Popconfirm title="确定清空所有已读消息？" onConfirm={clearRead} okText="清空" cancelText="取消">
            <Button size="small" danger>清空已读</Button>
          </Popconfirm>
        </Space>
      </div>
      {loading && items.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
      ) : items.length === 0 ? (
        <Empty description={filter === 'unread' ? '没有未读消息' : '暂无消息'} style={{ marginTop: 60 }} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.map(m => {
            const ic = msgIconOf(m)
            const t = MSG_TYPE_MAP[m.type] || MSG_TYPE_MAP.system
            return (
              <Card key={m.id} size="small" hoverable onClick={() => markRead(m)}
                style={{
                  borderRadius: 10, cursor: 'pointer',
                  borderLeft: `3px solid ${m.read ? '#f0f0f0' : ic.color}`,
                  opacity: m.read ? 0.72 : 1,
                }}>
                <div style={{ display: 'flex', gap: 12 }}>
                  <div style={{ fontSize: 20, color: ic.color, lineHeight: 1.5 }}>{ic.icon}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                      <div style={{ fontWeight: m.read ? 400 : 600, color: '#1f2329', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {m.title}
                        {!m.read && <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#ff4d4f', marginLeft: 6, verticalAlign: 'middle' }} />}
                      </div>
                      <Text type="secondary" style={{ fontSize: 12, flexShrink: 0 }}>{m.created_at}</Text>
                    </div>
                    <div style={{ whiteSpace: 'pre-wrap', color: '#4a4f59', fontSize: 13, lineHeight: 1.7, marginTop: 4, wordBreak: 'break-word' }}>
                      {m.content}
                    </div>
                    <div style={{ marginTop: 6 }}><Tag color={t.tag} style={{ marginInlineEnd: 0 }}>{t.label}</Tag></div>
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

function AuthPage({ onLogin, onRegistered, msgCtx }) {
  const [mode, setMode] = useState('login')
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()
  const submit = async () => {
    try {
      const v = await form.validateFields()
      setLoading(true)
      if (mode === 'login') {
        const j = await api('/api/auth/login', { method: 'POST', body: JSON.stringify(v) })
        onLogin(j.user)
      } else {
        const j = await api('/api/auth/register', { method: 'POST', body: JSON.stringify(v) })
        onRegistered(j.user)
      }
    } catch (e) {
      msgCtx && msgCtx.error(e.message)
    } finally { setLoading(false) }
  }
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'linear-gradient(135deg,#e6f0ff, #f5f7fa)', padding: '0 16px' }}>
      <Card style={{ width: '100%', maxWidth: 380, boxShadow: '0 6px 24px rgba(22,119,255,0.12)' }}>
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <img src="/static/logo.png" alt="马上签" style={{ width: 64, height: 64, objectFit: 'contain', marginBottom: 6 }} />
          <div style={{ fontSize: 26, fontWeight: 800, color: '#1677ff' }}>马上签</div>
          <Text type="secondary">登录后即可添加学习通账号并开启 24h 监控</Text>
        </div>
        <Tabs activeKey={mode} onChange={setMode} centered items={[
          { key: 'login', label: '登录' }, { key: 'register', label: '注册' },
        ]} />
        <Form form={form} layout="vertical" onFinish={submit}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" size="large" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<UserOutlined />} placeholder="密码" size="large" />
          </Form.Item>
          {mode === 'register' && (
            <Form.Item name="email" rules={[
              { required: true, message: '请输入QQ邮箱' },
              { type: 'email', message: '邮箱格式不正确' },
            ]} extra="用于接收签到成功/失败等通知邮件">
              <Input prefix={<MailOutlined />} placeholder="QQ邮箱（如 123456@qq.com）" size="large" />
            </Form.Item>
          )}
          <Button type="primary" block size="large" loading={loading} htmlType="submit">
            {mode === 'login' ? '登 录' : '注 册 并 登 录'}
          </Button>
        </Form>
        <Divider style={{ margin: '16px 0 12px' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>第一次使用？</Text>
        </Divider>
        <Button block size="large" icon={<ReadOutlined />} href="/help" target="_blank"
          style={{ borderColor: '#1677ff', color: '#1677ff', fontWeight: 600 }}>
          使用教程 · 3 分钟上手
        </Button>
      </Card>
      <div style={{ marginTop: 16, textAlign: 'center' }}>
        <a href="/help" target="_blank" style={{ color: '#8a94a6', fontSize: 13 }}>
          不会用？点这里查看图文使用教程 →
        </a>
      </div>
    </div>
  )
}

// ---------- 账号卡片 ----------
function AccountCard({ a, onToggle, onOpen, onRemove, onLogout, onCheck }) {
  const [checking, setChecking] = useState(false)
  const [checkInfo, setCheckInfo] = useState(null)   // {kind:'found'|'error', found?[], text?}
  const statusTag = a.need_relogin
    ? <Tag color="error">需重新登录</Tag>
    : a.logged_in
      ? <Tag color="success">已登录</Tag>
      : <Tag color="default">未登录</Tag>
  const monTag = a.monitoring && a.monitor_alive
    ? <Tag color="processing">监控中</Tag>
    : a.monitoring ? <Tag color="warning">线程异常</Tag> : <Tag>未监控</Tag>

  const runCheck = async () => {
    setChecking(true)
    setCheckInfo(null)
    try {
      const j = await onCheck(a)
      message.success(j.msg || '检查完成')
      if (j.found && j.found.length > 0) setCheckInfo({ kind: 'found', found: j.found })
    } catch (e) {
      message.error(e.message)
      setCheckInfo({ kind: 'error', text: e.message })
    } finally {
      setChecking(false)
    }
  }

  const resultTag = (r) => r === 'success'
    ? <Tag color="success">签到成功</Tag>
    : r === 'fail' ? <Tag color="error">签到失败</Tag> : <Tag color="orange">需手动</Tag>

  return (
    <Card
      title={<Space><Avatar style={{ background: '#1677ff' }}>{a.name ? a.name[0] : '学'}</Avatar>{a.name || a.acct_id}</Space>}
      extra={statusTag}
      actions={[
        <Tooltip title="配置/记录"><SettingOutlined key="s" onClick={() => onOpen(a, 'config')} /></Tooltip>,
        <Popconfirm title="退出该学习通账号？" onConfirm={() => onLogout(a)}><LogoutOutlined key="l" /></Popconfirm>,
        <Popconfirm title="移除该账号？" onConfirm={() => onRemove(a)}><CloseCircleTwoTone twoToneColor="#ff4d4f" key="r" /></Popconfirm>,
      ]}
    >
      <Space wrap>
        {monTag}
        {a.manual_today > 0 && <Tag color="orange">今日需手动 {a.manual_today}</Tag>}
        <Text type="secondary">课程 {a.courses}</Text>
        <Text type="secondary">记录 {a.records}</Text>
      </Space>
      <Divider style={{ margin: '12px 0' }} />
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <Switch checked={a.monitoring} onChange={(v) => onToggle(a, v)} disabled={!a.logged_in} />
          <Text>监控</Text>
        </Space>
        <Space>
          <Button size="small" onClick={() => onOpen(a, 'records')}>查看记录</Button>
          <Tooltip title="立即验证登录态并扫描一轮全部课程，不等待监控轮询">
            <Button size="small" type="primary" ghost icon={<ThunderboltOutlined />}
              loading={checking} disabled={!a.logged_in} onClick={runCheck}>立即检查</Button>
          </Tooltip>
        </Space>
      </Space>
      {a.need_relogin && <Alert type="warning" showIcon style={{ marginTop: 12 }} message="登录态已过期，请退出后重新扫码" />}
      {checkInfo && checkInfo.kind === 'error' && (
        <Alert type="error" showIcon style={{ marginTop: 12 }} message={checkInfo.text} />
      )}
      {checkInfo && checkInfo.kind === 'found' && (
        <Alert type="success" showIcon style={{ marginTop: 12 }}
          message={
            <div>
              <div style={{ fontWeight: 600 }}>本次检测到 {checkInfo.found.length} 个新签到：</div>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {checkInfo.found.map((f, i) => (
                  <li key={i} style={{ fontSize: 13, lineHeight: 1.9 }}>
                    [{f.course}] {f.activity}（{f.type}） {resultTag(f.result)}
                    {f.detail && f.result !== 'success' && <Text type="secondary" style={{ fontSize: 12 }}> {f.detail}</Text>}
                  </li>
                ))}
              </ul>
            </div>
          } />
      )}
    </Card>
  )
}

// ---------- 位置选点地图（Leaflet + 高德瓦片，无需 key） ----------
const MSQ_PIN_CSS = `
.leaflet-container{font-family:inherit;background:#eef3fa;}
.msq-pin{background:none;border:none;}
.msq-pin-dot{width:22px;height:22px;border-radius:50%;background:#1677ff;border:3px solid #fff;box-shadow:0 2px 8px rgba(22,119,255,.5);box-sizing:border-box;}
`
function LocationMapPicker({ lat, lng, onChange }) {
  const boxRef = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)
  const hasPos = lat !== '' && lng !== '' && isFinite(parseFloat(lat)) && isFinite(parseFloat(lng))

  const makeMarker = (la, ln) => {
    const m = L.marker([la, ln], {
      icon: L.divIcon({ className: 'msq-pin', html: '<div class="msq-pin-dot"></div>', iconSize: [22, 22], iconAnchor: [11, 11] }),
      draggable: true,
    })
    m.on('dragend', () => { const p = m.getLatLng(); onChange(p.lat.toFixed(6), p.lng.toFixed(6)) })
    return m
  }

  // 初始化地图（仅一次）
  useEffect(() => {
    if (mapRef.current || !boxRef.current) return
    const start = hasPos ? [parseFloat(lat), parseFloat(lng)] : [39.9092, 116.4074]
    const map = L.map(boxRef.current, { zoomControl: true, attributionControl: false })
      .setView(start, hasPos ? 16 : 10)
    L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
      { subdomains: ['1', '2', '3', '4'], maxZoom: 18 }).addTo(map)
    if (hasPos) markerRef.current = makeMarker(start[0], start[1]).addTo(map)
    map.on('click', e => {
      if (markerRef.current) map.removeLayer(markerRef.current)
      markerRef.current = makeMarker(e.latlng.lat, e.latlng.lng).addTo(map)
      onChange(e.latlng.lat.toFixed(6), e.latlng.lng.toFixed(6))
    })
    mapRef.current = map
    const t = setTimeout(() => map.invalidateSize(), 300)
    return () => clearTimeout(t)
  }, [])

  // 外部坐标变化（手输 / 当前定位）时同步标记与视图
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (hasPos) {
      const la = parseFloat(lat), ln = parseFloat(lng)
      const cur = markerRef.current && markerRef.current.getLatLng()
      if (!cur || Math.abs(cur.lat - la) > 5e-6 || Math.abs(cur.lng - ln) > 5e-6) {
        if (markerRef.current) map.removeLayer(markerRef.current)
        markerRef.current = makeMarker(la, ln).addTo(map)
        map.setView([la, ln], Math.max(map.getZoom(), 16))
      }
    } else if (markerRef.current) {
      map.removeLayer(markerRef.current)
      markerRef.current = null
    }
  }, [lat, lng])

  return (
    <div>
      <style>{MSQ_PIN_CSS}</style>
      <div ref={boxRef} style={{ height: 260, borderRadius: 8, overflow: 'hidden', border: '1px solid #e8eef7' }} />
    </div>
  )
}


// ---------- 配置 ----------
function ConfigTab({ detail, onSave, onRefreshCourses, refreshing }) {
  const [form] = Form.useForm()
  const locLat = Form.useWatch('loc_lat', form)
  const locLng = Form.useWatch('loc_lng', form)
  useEffect(() => {
    form.setFieldsValue({
      interval: detail.config?.interval || 45,
      serverchan_key: detail.config?.serverchan_key || '',
      enabled_courses: detail.config?.enabled_courses || [],
      loc_enabled: !!detail.config?.loc_enabled,
      loc_lat: detail.config?.loc_lat || '',
      loc_lng: detail.config?.loc_lng || '',
      loc_addr: detail.config?.loc_addr || '',
    })
  }, [detail])

  const useMyLoc = () => {
    if (!navigator.geolocation) { message.error('当前浏览器不支持定位'); return }
    message.info('正在获取定位，请在浏览器弹窗中允许…')
    navigator.geolocation.getCurrentPosition(
      pos => {
        form.setFieldsValue({
          loc_lat: pos.coords.latitude.toFixed(6),
          loc_lng: pos.coords.longitude.toFixed(6),
        })
        message.success('已填入当前定位（GPS 坐标）')
      },
      err => message.error('定位失败：' + (err.message || '请检查定位权限')),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    )
  }

  const allCourses = detail.courses || []
  return (
    <Form form={form} layout="vertical" onFinish={onSave}>
      <Form.Item name="interval" label="检测间隔（秒）" rules={[{ required: true }]}>
        <InputNumber min={15} max={600} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name="serverchan_key" label="Server 酱 SendKey（可选，用于推送提醒）">
        <Input placeholder="SCTxxxxxxxx" />
      </Form.Item>
      <Form.Item
        name="enabled_courses"
        label={`仅监控以下课程（共 ${allCourses.length} 门，留空=全部）`}
        extra={onRefreshCourses ? (
          <Button size="small" icon={<ReloadOutlined />} loading={refreshing}
            onClick={onRefreshCourses} style={{ marginTop: 4 }}>刷新课程</Button>
        ) : null}
      >
        <Select mode="multiple" allowClear placeholder="选择课程" options={allCourses.map(c => ({ value: c.key, label: `${c.courseName}${c.className ? '(' + c.className + ')' : ''}` }))} />
      </Form.Item>

      <Divider orientation="left" style={{ marginTop: 8 }}>位置模拟签到</Divider>
      <Form.Item name="loc_enabled" label="启用位置模拟" valuePropName="checked"
        extra="开启后，检测到「位置签到」时自动提交下方坐标完成签到，无需手机在旁。">
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>
      <Form.Item label="在地图上选点（点击地图或拖动蓝色标记）">
        <LocationMapPicker
          lat={locLat || ''}
          lng={locLng || ''}
          onChange={(la, ln) => form.setFieldsValue({ loc_lat: la, loc_lng: ln })}
        />
      </Form.Item>
      <Space wrap align="start" style={{ marginBottom: 8 }}>
        <Form.Item name="loc_lat" label="纬度" style={{ marginBottom: 0, minWidth: 150 }}>
          <Input placeholder="如 39.9092" />
        </Form.Item>
        <Form.Item name="loc_lng" label="经度" style={{ marginBottom: 0, minWidth: 150 }}>
          <Input placeholder="如 116.4074" />
        </Form.Item>
      </Space>
      <div style={{ marginBottom: 12 }}>
        <Button size="small" onClick={useMyLoc}>用当前定位填充</Button>
        <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
          地图为高德坐标系(GCJ-02)，当前定位为 GPS(WGS-84)；若签到提示距离不符，两种坐标都可试。
        </Text>
      </div>
      <Form.Item name="loc_addr" label="地址备注（可选，随坐标一起提交）">
        <Input placeholder="如 综合楼 301" />
      </Form.Item>

      <Button type="primary" htmlType="submit" block>保存配置</Button>
    </Form>
  )
}

// ---------- 记录 ----------
function RecordsTab({ records }) {
  if (!records.length) return <Empty description="暂无签到记录" />
  return (
    <List dataSource={records} renderItem={r => (
      <List.Item>
        <List.Item.Meta
          avatar={r.result === 'success' ? <CheckCircleTwoTone twoToneColor="#52c41a" />
            : r.result === 'manual' ? <ExclamationCircleTwoTone twoToneColor="#faad14" />
              : <CloseCircleTwoTone twoToneColor="#ff4d4f" />}
          title={`${r.activity || ''} · ${r.type}`}
          description={<><div>{r.course}</div><div style={{ fontSize: 12, color: '#999' }}>{r.time} · {r.detail}</div></>}
        />
      </List.Item>
    )} />
  )
}

// ---------- 工单列表 ----------
function TicketList({ tickets, onOpen }) {
  if (!tickets.length) return <Empty description="还没有工单" style={{ marginTop: 80 }} />
  const color = { open: 'default', in_progress: 'processing', resolved: 'success', closed: 'default' }
  return (
    <List
      itemLayout="horizontal"
      dataSource={tickets}
      renderItem={t => (
        <List.Item actions={[<Button key="o" type="link" onClick={() => onOpen(t)}>查看</Button>]}>
          <List.Item.Meta
            title={<Space>{t.subject} <Tag color={color[t.status]}>{t.status_label}</Tag></Space>}
            description={<Space wrap>
              <Text type="secondary">#{t.id}</Text>
              <Tag>{t.category_label}</Tag>
              <Text type="secondary">优先级 {t.priority_label}</Text>
              <Text type="secondary">更新 {t.updated_at}</Text>
              {t.reply_count > 0 && <Badge count={t.reply_count} size="small" />}
            </Space>}
          />
        </List.Item>
      )}
    />
  )
}

// ---------- 工单表单 ----------
function TicketForm({ formRef, onSubmit }) {
  const [form] = Form.useForm()
  useEffect(() => { if (formRef) formRef.current = form }, [form])
  return (
    <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ category: 'bug' }}>
      <Form.Item name="subject" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
        <Input placeholder="一句话描述问题" maxLength={50} />
      </Form.Item>
      <Form.Item name="category" label="类型" rules={[{ required: true }]}>
        <Select options={[
          { value: 'bug', label: '故障/BUG' }, { value: 'feature', label: '功能建议' },
          { value: 'question', label: '使用咨询' }, { value: 'other', label: '其他' },
        ]} />
      </Form.Item>
      <Form.Item name="content" label="详细描述" rules={[{ required: true, message: '请输入内容' }]}>
        <Input.TextArea rows={5} placeholder="请尽量描述清楚：什么时间、什么账号、发生了什么" />
      </Form.Item>
    </Form>
  )
}

// ---------- 工单详情 ----------
function TicketDetail({ t, reply, setReply, onSend }) {
  return (
    <div>
      <Space wrap>
        <Tag color={t.status === 'resolved' ? 'success' : t.status === 'in_progress' ? 'processing' : 'default'}>{t.status_label}</Tag>
        <Tag>{t.category_label}</Tag>
        <Text>优先级：{t.priority_label}</Text>
      </Space>
      <Card size="small" style={{ marginTop: 12, background: '#fafafa' }}>
        <div style={{ whiteSpace: 'pre-wrap' }}>{t.content}</div>
        <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>提交于 {t.created_at}</div>
      </Card>
      <Divider>对话记录</Divider>
      {!t.replies.length && <Empty description="暂无回复" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      <List dataSource={t.replies} renderItem={r => (
        <List.Item>
          <List.Item.Meta
            title={<Space>{r.role === 'admin' ? <Tag color="blue">管理员</Tag> : <Tag>{r.from}</Tag>}<Text type="secondary" style={{ fontSize: 12 }}>{r.time}</Text></Space>}
            description={<div style={{ whiteSpace: 'pre-wrap' }}>{r.message}</div>}
          />
        </List.Item>
      )} />
      <Input.TextArea rows={3} value={reply} onChange={e => setReply(e.target.value)} placeholder="追加回复…" style={{ marginTop: 12 }} />
      <Button type="primary" block style={{ marginTop: 8 }} onClick={onSend}>发送回复</Button>
    </div>
  )
}

// ---------- 个人主页 / 个人中心 ----------
function ProfileView({ user, accounts, tickets, onOpenTicket, onNewTicket, onUserUpdate, isMobile }) {
  const [msg, msgCtx] = message.useMessage()
  const [editOpen, setEditOpen] = useState(false)
  const [editSaving, setEditSaving] = useState(false)
  const [editForm] = Form.useForm()
  const total = (accounts || []).length
  const online = (accounts || []).filter(a => a.logged_in).length
  const monitoring = (accounts || []).filter(a => a.monitoring && a.monitor_alive).length
  const myTickets = (tickets || []).length
  const stats = [
    { t: '学习通账号', v: total, c: '#1677ff' },
    { t: '在线', v: online, c: '#52c41a' },
    { t: '监控中', v: monitoring, c: '#1677ff' },
    { t: '我的工单', v: myTickets, c: '#faad14' },
  ]
  const saveProfile = async () => {
    const v = await editForm.validateFields()
    setEditSaving(true)
    try {
      const body = { email: (v.email || '').trim() }
      if (v.password && v.password.trim()) body.password = v.password.trim()
      const j = await api('/api/auth/profile', { method: 'PUT', body: JSON.stringify(body) })
      msg.success('资料已更新')
      onUserUpdate && onUserUpdate(j.user)
      setEditOpen(false)
      editForm.resetFields()
    } catch (e) {
      msg.error(e.message || '更新失败')
    } finally { setEditSaving(false) }
  }
  return (
    <div>
      {msgCtx}
      <Card style={{ marginBottom: 16 }} title="个人中心"
        extra={<Button size="small" icon={<SettingOutlined />} onClick={() => {
          editForm.setFieldsValue({ email: user.email || '' })
          setEditOpen(true)
        }}>编辑资料</Button>}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <Avatar size={64} style={{ background: '#1677ff', fontSize: 26 }}>{user.username ? user.username[0] : '我'}</Avatar>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{user.username}</div>
            <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <Tag color={user.role === 'admin' ? 'blue' : 'default'}>{user.role === 'admin' ? '管理员' : '普通用户'}</Tag>
              <Text type="secondary" style={{ fontSize: 13 }}><MailOutlined /> {user.email || '未绑定邮箱'}</Text>
            </div>
          </div>
        </div>
        <Divider style={{ margin: '16px 0 8px' }} />
        <List size="small" dataSource={[
          { k: '用户名', v: user.username },
          { k: 'QQ邮箱', v: user.email || '未绑定' },
          { k: '角色', v: user.role === 'admin' ? '管理员' : '普通用户' },
          { k: '注册时间', v: user.created_at || '-' },
        ]} renderItem={it => (
          <List.Item>
            <Text type="secondary">{it.k}</Text>
            <span>{it.v}</span>
          </List.Item>
        )} />
      </Card>

      <Modal title="编辑个人资料" open={editOpen} onCancel={() => setEditOpen(false)}
        onOk={saveProfile} confirmLoading={editSaving} okText="保存" width={isMobile ? '92vw' : 440}>
        <Form form={editForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="email" label="QQ邮箱" rules={[
            { required: true, message: '请输入QQ邮箱' },
            { type: 'email', message: '邮箱格式不正确' },
          ]} extra="签到成功/失败等通知将发送到此邮箱">
            <Input prefix={<MailOutlined />} placeholder="QQ邮箱（如 123456@qq.com）" />
          </Form.Item>
          <Form.Item name="password" label="新密码" rules={[{ min: 6, message: '至少 6 位' }]} extra="留空则不修改密码">
            <Input.Password prefix={<UserOutlined />} placeholder="留空表示不修改" />
          </Form.Item>
        </Form>
      </Modal>

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'repeat(2,1fr)' : 'repeat(4,1fr)', gap: 12, marginBottom: 16 }}>
        {stats.map(s => (
          <Card key={s.t} size="small"><Statistic title={s.t} value={s.v} valueStyle={{ color: s.c }} /></Card>
        ))}
      </div>

      <Card title="我的工单" style={{ marginBottom: 16 }}
        extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={onNewTicket}>提交工单</Button>}>
        {myTickets === 0 ? <Empty description="暂无工单" /> : <TicketList tickets={tickets} onOpen={onOpenTicket} />}
      </Card>

      <Card title="使用帮助" style={{ marginBottom: 16 }}>
        <List size="small">
          <List.Item>
            <List.Item.Meta
              avatar={<ReadOutlined style={{ fontSize: 18, color: '#1677ff' }} />}
              title={<a href="/help" target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>图文使用教程</a>}
              description="3 分钟快速上手：注册登录、扫码添加账号、签到规则、邮件通知、常见问题"
            />
            <Button type="primary" size="small" href="/help" target="_blank">查看教程</Button>
          </List.Item>
        </List>
      </Card>

      <Card title="版本信息" style={{ marginBottom: 16 }}>
        <List size="small" dataSource={[
          { k: '产品名称', v: '马上签' },
          { k: '版本', v: APP_VERSION },
          { k: '类型', v: '超星学习通自动签到 · 多用户版' },
        ]} renderItem={it => (
          <List.Item>
            <Text type="secondary">{it.k}</Text>
            <span>{it.v}</span>
          </List.Item>
        )} />
      </Card>

      <div style={{ textAlign: 'center', color: '#999', fontSize: 12, padding: '8px 0 4px' }}>
        © 2026 马上签 · 仅供学习交流使用<br />
        使用问题请在「我的工单」中反馈
      </div>
    </div>
  )
}
