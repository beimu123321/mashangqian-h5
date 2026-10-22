import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  Layout, Grid, Card, Button, Modal, Table, Tag, Switch, Input, InputNumber, Radio, Form, message, Drawer,
  List, Empty, Spin, Statistic, Space, Typography, Popconfirm, Select, Badge,
  Avatar, Row, Col, Menu, Divider, Alert,
} from 'antd'
import {
  DashboardOutlined, TeamOutlined, AccountBookOutlined, MessageOutlined,
  FileTextOutlined, LogoutOutlined, PlusOutlined, ReloadOutlined, MenuOutlined,
  CheckCircleTwoTone, ExclamationCircleTwoTone, CloseCircleTwoTone,
  NotificationOutlined, HistoryOutlined, SettingOutlined, SearchOutlined,
  MobileOutlined, CloudDownloadOutlined, MailOutlined, PictureOutlined,
} from '@ant-design/icons'

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
  if (j && j.ok === false) {
    const err = new Error(j.msg || '请求失败')
    err.payload = j   // 便于调用方读取 retry_after 等附加字段
    throw err
  }
  if (!res.ok) throw new Error(j.msg || `HTTP ${res.status}`)
  return j
}

const TICKET_STATUS = {
  open: { label: '待处理', color: 'default' },
  in_progress: { label: '处理中', color: 'processing' },
  resolved: { label: '已解决', color: 'success' },
  closed: { label: '已关闭', color: 'default' },
}
const TICKET_CATEGORY = { bug: '故障/BUG', feature: '功能建议', question: '使用咨询', other: '其他' }
const TICKET_PRIORITY = { low: '低', normal: '普通', high: '高' }

export default function App() {
  const [user, setUser] = useState(null)
  const [bootstrap, setBootstrap] = useState(true)
  const [menu, setMenu] = useState('overview')
  const [msg, ctx] = message.useMessage()
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const [drawerOpen, setDrawerOpen] = useState(false)

  const [stats, setStats] = useState(null)
  const [users, setUsers] = useState([])
  const [superAdmin, setSuperAdmin] = useState('')
  const [accounts, setAccounts] = useState([])
  const [tickets, setTickets] = useState([])
  const [ticketFilter, setTicketFilter] = useState('')
  const [logs, setLogs] = useState([])
  const [logAfter, setLogAfter] = useState(0)
  const [announcements, setAnnouncements] = useState([])
  const [records, setRecords] = useState([])
  const [signStats, setSignStats] = useState(null)
  const [recOwner, setRecOwner] = useState('')
  const [recResult, setRecResult] = useState('')
  const [settings, setSettings] = useState(null)
  const [appReleases, setAppReleases] = useState([])
  const [splash, setSplash] = useState(null)
  const [userSearch, setUserSearch] = useState('')

  const [userModal, setUserModal] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [ticketDrawer, setTicketDrawer] = useState(null)
  const [annoModal, setAnnoModal] = useState(false)
  const [editingAnno, setEditingAnno] = useState(null)
  const [relModal, setRelModal] = useState(false)
  const [editingRel, setEditingRel] = useState(null)
  const [checking, setChecking] = useState('')
  const af = useRef(null)
  const rf = useRef(null)

  const uf = useRef(null)
  const autoTimer = useRef(null)

  const loadMe = async () => {
    try {
      const j = await api('/api/auth/me')
      if (j.logged_in && j.user.role === 'admin') setUser(j.user)
      else setUser(false)
    } catch { setUser(false) } finally { setBootstrap(false) }
  }
  useEffect(() => { loadMe() }, [])

  const refresh = async (m = menu) => {
    if (!user) return
    try {
      if (m === 'overview') setStats((await api('/api/admin/stats')).stats)
      if (m === 'users') { const r = await api('/api/admin/users'); setUsers(r.users); setSuperAdmin(r.super || '') }
      if (m === 'accounts') setAccounts((await api('/api/admin/accounts')).accounts)
      if (m === 'tickets') {
        const q = ticketFilter ? `?status=${ticketFilter}` : ''
        setTickets((await api('/api/admin/tickets' + q)).tickets)
      }
      if (m === 'announcements') setAnnouncements((await api('/api/admin/announcements')).announcements)
      if (m === 'records') {
        const p = new URLSearchParams()
        if (recOwner) p.set('owner', recOwner)
        if (recResult) p.set('result', recResult)
        const j = await api('/api/admin/records?' + p.toString())
        setRecords(j.records || [])
        setSignStats(j.sign_stats || null)
      }
      if (m === 'settings') setSettings((await api('/api/admin/settings')).settings)
      if (m === 'appReleases') setAppReleases((await api('/api/admin/app-releases')).releases)
      if (m === 'splash') setSplash((await api('/api/admin/splash')).splash)
    } catch (e) { msg.error(e.message) }
  }

  useEffect(() => {
    if (!user) return
    refresh(menu)
  }, [user, menu, ticketFilter, recOwner, recResult])

  // logs 轮询
  useEffect(() => {
    if (!user || menu !== 'logs') return
    const load = async () => {
      try {
        const j = await api('/api/admin/logs?after=' + logAfter)
        if (j.logs && j.logs.length) {
          setLogs(prev => [...prev, ...j.logs].slice(-500))
          setLogAfter(j.logs[j.logs.length - 1].seq)
        }
      } catch {}
    }
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [user, menu, logAfter])

  const doLogout = async () => {
    await api('/api/auth/logout', { method: 'POST' })
    setUser(false)
    msg.success('已退出')
  }

  if (bootstrap) return <div style={{ display: 'grid', placeItems: 'center', height: '100%' }}><Spin size="large" /></div>
  if (!user) return <LoginPage onOk={setUser} msgCtx={ctx} />

  const menuItems = [
    { key: 'overview', icon: <DashboardOutlined />, label: '概览' },
    { key: 'users', icon: <TeamOutlined />, label: '用户管理' },
    { key: 'accounts', icon: <AccountBookOutlined />, label: '学习通账号' },
    { key: 'records', icon: <HistoryOutlined />, label: '签到记录' },
    { key: 'tickets', icon: <MessageOutlined />, label: '工单管理' },
    { key: 'announcements', icon: <NotificationOutlined />, label: '公告管理' },
    { key: 'email', icon: <MailOutlined />, label: '邮件群发' },
    { key: 'appReleases', icon: <MobileOutlined />, label: 'APP版本' },
    { key: 'splash', icon: <PictureOutlined />, label: 'APP闪屏' },
    { key: 'settings', icon: <SettingOutlined />, label: '系统设置' },
    { key: 'logs', icon: <FileTextOutlined />, label: '系统日志' },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {ctx}
      {!isMobile && (
      <Sider theme="light" width={200} style={{ borderRight: '1px solid #f0f0f0' }}>
        <div style={{ padding: '20px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <img src="/static/logo.png" alt="马上签" style={{ width: 32, height: 32, objectFit: 'contain' }} />
          <span style={{ fontWeight: 700, color: '#1677ff', fontSize: 16 }}>马上签 · 后台</span>
        </div>
        <Menu mode="inline" selectedKeys={[menu]} onClick={e => setMenu(e.key)} items={menuItems} />
        <div style={{ position: 'absolute', bottom: 16, left: 16, right: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>管理员：{user.username}</Text>
            <Button block icon={<LogoutOutlined />} onClick={doLogout}>退出登录</Button>
          </Space>
        </div>
      </Sider>
      )}
      {isMobile && (
        <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} placement="left" title="马上签 · 后台" width="80vw">          <Menu mode="inline" selectedKeys={[menu]} onClick={e => { setMenu(e.key); setDrawerOpen(false) }} items={menuItems} />
          <div style={{ marginTop: 24 }}>
            <Button block icon={<LogoutOutlined />} onClick={() => { doLogout(); setDrawerOpen(false) }}>退出登录</Button>
          </div>
        </Drawer>
      )}
      <Layout>
        <Header style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: isMobile ? '0 12px' : '0 24px' }}>
          <Space>
            {isMobile && <Button type="text" icon={<MenuOutlined />} onClick={() => setDrawerOpen(true)} />}
            <Title level={isMobile ? 5 : 4} style={{ margin: 0 }}>{menuItems.find(m => m.key === menu)?.label}</Title>
          </Space>
          <Space size={isMobile ? 4 : 'small'} wrap>
            {menu === 'users' && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingUser(null); setUserModal(true) }}>{!isMobile && '新建用户'}</Button>}
            {menu === 'accounts' && <Button icon={<ReloadOutlined />} onClick={() => refresh('accounts')}>{!isMobile && '刷新'}</Button>}
            {menu === 'tickets' && <Button icon={<ReloadOutlined />} onClick={() => refresh('tickets')}>{!isMobile && '刷新'}</Button>}
            {menu === 'records' && <Button icon={<ReloadOutlined />} onClick={() => refresh('records')}>{!isMobile && '刷新'}</Button>}
            {menu === 'announcements' && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingAnno(null); setAnnoModal(true) }}>{!isMobile && '新建公告'}</Button>}
            {menu === 'announcements' && <Button icon={<ReloadOutlined />} onClick={() => refresh('announcements')}>{!isMobile && '刷新'}</Button>}
            {menu === 'appReleases' && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingRel(null); setRelModal(true) }}>{!isMobile && '发布新版本'}</Button>}
            {menu === 'appReleases' && <Button icon={<ReloadOutlined />} onClick={() => refresh('appReleases')}>{!isMobile && '刷新'}</Button>}
            {menu === 'logs' && <Button icon={<ReloadOutlined />} onClick={() => { setLogs([]); setLogAfter(0) }}>{!isMobile && '清空重载'}</Button>}
          </Space>
        </Header>
        <Content style={{ padding: isMobile ? 12 : 24 }}>
          {menu === 'overview' && <Overview stats={stats} onJump={setMenu} isMobile={isMobile} />}
          {menu === 'users' && <UsersTab users={users} search={userSearch} setSearch={setUserSearch} refresh={refresh} msg={msg} onEdit={(u) => { setEditingUser(u); setUserModal(true) }} superAdmin={superAdmin} />}
          {menu === 'accounts' && <AccountsTab accounts={accounts} refresh={() => refresh('accounts')} msg={msg} checking={checking} setChecking={setChecking} />}
          {menu === 'records' && <RecordsTab records={records} signStats={signStats} owner={recOwner} setOwner={setRecOwner} result={recResult} setResult={setRecResult} users={users} />}
          {menu === 'tickets' && <TicketsTab tickets={tickets} filter={ticketFilter} setFilter={setTicketFilter} onOpen={setTicketDrawer} refresh={() => refresh('tickets')} msg={msg} />}
          {menu === 'announcements' && <AnnouncementsTab announcements={announcements} refresh={() => refresh('announcements')} onEdit={(a) => { setEditingAnno(a); setAnnoModal(true) }} msg={msg} />}
          {menu === 'email' && <EmailTab users={users} msg={msg} isMobile={isMobile} />}
          {menu === 'appReleases' && <AppReleasesTab releases={appReleases} refresh={() => refresh('appReleases')} onEdit={(r) => { setEditingRel(r); setRelModal(true) }} msg={msg} />}
          {menu === 'splash' && <SplashTab splash={splash} refresh={() => refresh('splash')} msg={msg} />}
          {menu === 'settings' && <SettingsTab settings={settings} refresh={refresh} msg={msg} />}
          {menu === 'logs' && <LogsTab logs={logs} />}
        </Content>
      </Layout>

      {/* 新建/编辑用户 */}
      <Modal title={editingUser ? `编辑用户 ${editingUser.username}` : '新建站点用户'} open={userModal}
        onCancel={() => { setUserModal(false); setEditingUser(null) }} width={isMobile ? '92vw' : 520}
        onOk={() => uf.current?.submit()} okText={editingUser ? '保存' : '创建'} destroyOnClose>
        <UserForm uf={uf} editing={editingUser}
          onCreated={() => { setUserModal(false); setEditingUser(null); refresh('users') }} />
      </Modal>

      {/* 公告新建/编辑 */}
      <Modal title={editingAnno ? `编辑公告 #${editingAnno.id}` : '新建公告'} open={annoModal} width={isMobile ? '92vw' : 520}
        onCancel={() => setAnnoModal(false)} onOk={() => af.current?.submit()} okText="保存" destroyOnClose>
        <AnnouncementForm af={af} editing={editingAnno}
          onSaved={() => { setAnnoModal(false); setEditingAnno(null); refresh('announcements') }} />
      </Modal>

      {/* APP版本发布/编辑 */}
      <Modal title={editingRel ? `编辑版本 ${editingRel.version_name}` : '发布新 APP 版本'} open={relModal} width={isMobile ? '92vw' : 520}
        onCancel={() => { setRelModal(false); setEditingRel(null) }} onOk={() => rf.current?.submit()} okText="保存" destroyOnClose>
        <AppReleaseForm rf={rf} editing={editingRel}
          onSaved={() => { setRelModal(false); setEditingRel(null); refresh('appReleases') }} />
      </Modal>

      {/* 工单详情 */}
      <Drawer title={ticketDrawer ? `工单 #${ticketDrawer.id} ${ticketDrawer.subject}` : ''} width={isMobile ? '92vw' : 600} open={!!ticketDrawer} onClose={() => setTicketDrawer(null)}>
        {ticketDrawer && <TicketDrawer t={ticketDrawer} refresh={() => refresh('tickets')} onClose={() => setTicketDrawer(null)} msg={msg} />}
      </Drawer>
    </Layout>
  )
}

// ---------- 管理员登录 ----------
function LoginPage({ onOk, msgCtx }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const submit = async () => {
    try {
      const v = await form.validateFields()
      setLoading(true)
      const j = await api('/api/auth/login', { method: 'POST', body: JSON.stringify(v) })
      if (j.user.role !== 'admin') { msgCtx.error('该账号不是管理员'); return }
      onOk(j.user)
    } catch (e) { msgCtx.error(e.message) } finally { setLoading(false) }
  }
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'linear-gradient(135deg,#e6f0ff,#f5f7fa)', padding: '0 16px' }}>
      <Card style={{ width: '100%', maxWidth: 360, boxShadow: '0 6px 24px rgba(22,119,255,0.12)' }}>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <img src="/static/logo.png" alt="马上签" style={{ width: 56, height: 56, objectFit: 'contain', marginBottom: 6 }} />
          <Title level={4} style={{ margin: 0, color: '#1677ff' }}>后台管理登录</Title>
        </div>
        <Form form={form} layout="vertical" onFinish={submit}>
          <Form.Item name="username" rules={[{ required: true }]}><Input placeholder="管理员账号" size="large" /></Form.Item>
          <Form.Item name="password" rules={[{ required: true }]}><Input.Password placeholder="密码" size="large" /></Form.Item>
          <Button type="primary" block size="large" loading={loading} htmlType="submit">登 录</Button>
        </Form>
      </Card>
    </div>
  )
}

// ---------- 概览 ----------
function Overview({ stats, onJump, isMobile }) {
  if (!stats) return <Spin />
  const items = [
    { t: '站点用户', v: stats.site_users, u: '人', j: 'users' },
    { t: '学习通账号', v: stats.accounts, u: '个', j: 'accounts' },
    { t: '在线账号', v: stats.accounts_online, u: '个', c: '#52c41a' },
    { t: '监控中', v: stats.accounts_monitoring, u: '个', c: '#1677ff' },
    { t: '今日签到成功', v: stats.today_success, u: '次', j: 'records', c: '#52c41a' },
    { t: '今日签到失败', v: stats.today_fail, u: '次', j: 'records', c: '#ff4d4f' },
    { t: '今日需手动', v: stats.today_manual, u: '次', j: 'records', c: '#faad14' },
    { t: '待处理工单', v: stats.tickets_open, u: '条', j: 'tickets', c: '#faad14' },
    { t: '启用公告', v: stats.announcements, u: '条', j: 'announcements', c: '#722ed1' },
    { t: '累计签到记录', v: stats.total_records, u: '条', j: 'records' },
    { t: '运行时长', v: Math.floor(stats.uptime / 3600), u: '小时' },
  ]
  return (
    <Row gutter={16}>
      {items.map((it, i) => (
        <Col xs={12} sm={8} md={8} lg={6} key={i} style={{ marginBottom: 16 }}>
          <Card hoverable={!!it.j} onClick={() => it.j && onJump(it.j)}>
            <Statistic title={it.t} value={it.v} suffix={it.u} valueStyle={{ color: it.c || '#1677ff', fontSize: isMobile ? 20 : 24 }} />
          </Card>
        </Col>
      ))}
    </Row>
  )
}

// ---------- 用户管理 ----------
function UsersTab({ users, search, setSearch, refresh, msg, onEdit, superAdmin }) {
  const filtered = (users || []).filter(u =>
    !search || u.username.includes(search) || (u.email || '').includes(search))
  const columns = [
    { title: '用户名', dataIndex: 'username', render: (v) => <Space><Avatar style={{ background: '#1677ff' }}>{v[0]}</Avatar>{v}{v === superAdmin && <Tag color="gold">管理员</Tag>}</Space> },
    { title: '角色', dataIndex: 'role', render: r => <Tag color={r === 'admin' ? 'blue' : 'default'}>{r === 'admin' ? '管理员' : '普通用户'}</Tag> },
    { title: 'QQ邮箱', dataIndex: 'email', render: v => v || <Text type="secondary">未绑定</Text> },
    { title: '学习通账号', dataIndex: 'accounts' },
    { title: '在线', dataIndex: 'online' },
    { title: '创建时间', dataIndex: 'created_at' },
    { title: '禁用', dataIndex: 'disabled', render: (d, r) => <Switch checked={d} disabled={r.username === superAdmin} onChange={async v => { await api(`/api/admin/users/${r.username}/disable`, { method: 'POST', body: JSON.stringify({ disabled: v }) }); refresh() }} /> },
    { title: '操作', render: (_, r) => <Space>
      <Button size="small" onClick={() => onEdit(r)}>编辑</Button>
      <Popconfirm title="删除该用户及其账号？" onConfirm={async () => { await api(`/api/admin/users/${r.username}`, { method: 'DELETE' }); msg.success('已删除'); refresh() }}><Button danger size="small" disabled={r.username === superAdmin}>删除</Button></Popconfirm>
    </Space> },
  ]
  return (
    <>
      <Input allowClear placeholder="搜索用户名 / QQ邮箱" prefix={<SearchOutlined />} style={{ width: 260, marginBottom: 16 }}
        value={search} onChange={e => setSearch(e.target.value)} />
      <Table rowKey="username" dataSource={filtered} columns={columns} pagination={false} scroll={{ x: 'max-content' }} />
    </>
  )
}

// ---------- 学习通账号 ----------
function AccountsTab({ accounts, refresh, msg, checking, setChecking }) {
  const [cds, setCds] = useState({})   // acct_id -> 立即检查冷却剩余秒数
  // 冷却倒计时：每秒对每个在冷却中的账号减一
  useEffect(() => {
    const has = Object.values(cds).some(v => v > 0)
    if (!has) return
    const timer = setTimeout(() => setCds(m => {
      const next = {}
      for (const k in m) if (m[k] > 0) next[k] = m[k] - 1
      return next
    }), 1000)
    return () => clearTimeout(timer)
  }, [cds])
  const doCheck = async (r) => {
    if (checking || (cds[r.acct_id] || 0) > 0) return
    setChecking(r.acct_id)
    try {
      const j = await api(`/api/admin/accounts/${r.acct_id}/check`, { method: 'POST' })
      msg.success(`已对 ${r.name || r.acct_id} 触发一次立即检测`)
      setCds(m => ({ ...m, [r.acct_id]: j.retry_after || 60 }))
    } catch (e) {
      if (e.payload && e.payload.retry_after) setCds(m => ({ ...m, [r.acct_id]: e.payload.retry_after }))
      msg.error(e.message)
    } finally { setChecking('') }
  }
  const doLogout = async (r) => {
    await api(`/api/admin/accounts/${r.acct_id}/logout`, { method: 'POST' })
    msg.success(`已强制下线 ${r.name || r.acct_id}`)
    refresh()
  }
  const columns = [
    { title: '姓名', dataIndex: 'name', render: (v, r) => v || r.acct_id },
    { title: '所属用户', dataIndex: 'owner' },
    { title: '登录态', dataIndex: 'logged_in', render: v => v ? <Tag color="success">在线</Tag> : <Tag>离线</Tag> },
    { title: '监控', dataIndex: 'monitoring', render: (v, r) => v ? <Tag color="processing">监控中</Tag> : <Tag>未监控</Tag> },
    { title: '课程', dataIndex: 'courses' },
    { title: '记录', dataIndex: 'records' },
    { title: '今日需手动', dataIndex: 'manual_today', render: v => v > 0 ? <Tag color="orange">{v}</Tag> : v },
    { title: '操作', render: (_, r) => <Space wrap>
      <Switch checked={r.monitoring} disabled={!r.logged_in} onChange={async v => { await api(`/api/admin/accounts/${r.acct_id}/monitor`, { method: 'POST', body: JSON.stringify({ on: v }) }); refresh() }} />
      <Button size="small" loading={checking === r.acct_id}
        disabled={!r.logged_in || (cds[r.acct_id] || 0) > 0}
        onClick={() => doCheck(r)}>
        {(cds[r.acct_id] || 0) > 0 ? `请等待 ${cds[r.acct_id]}s` : '立即检查'}
      </Button>
      <Popconfirm title="强制下线该账号？监控将暂停，需用户重新扫码。" onConfirm={() => doLogout(r)}><Button size="small" disabled={!r.logged_in}>强制下线</Button></Popconfirm>
      <Popconfirm title="删除该账号？" onConfirm={async () => { await api(`/api/admin/accounts/${r.acct_id}`, { method: 'DELETE' }); msg.success('已删除'); refresh() }}><Button danger size="small">删除</Button></Popconfirm>
    </Space> },
  ]
  return <Table rowKey="acct_id" dataSource={accounts} columns={columns} pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
}

// ---------- 全局签到记录 ----------
const REC_RESULT = {
  success: { label: '成功', color: 'success' },
  fail: { label: '失败', color: 'error' },
  manual: { label: '需手动', color: 'warning' },
}

function RecordsTab({ records, signStats, owner, setOwner, result, setResult, users }) {
  const columns = [
    { title: '时间', dataIndex: 'time', width: 150 },
    { title: '账号', dataIndex: 'acct_name', render: (v, r) => <Space direction="vertical" size={0}><Text strong>{v || r.acct_id}</Text><Text type="secondary" style={{ fontSize: 12 }}>{r.owner}</Text></Space> },
    { title: '科目', dataIndex: 'course', ellipsis: true },
    { title: '活动', dataIndex: 'activity', ellipsis: true },
    { title: '类型', dataIndex: 'type', render: v => <Tag>{v}</Tag> },
    { title: '结果', dataIndex: 'result', render: v => <Tag color={REC_RESULT[v]?.color}>{REC_RESULT[v]?.label || v}</Tag> },
    { title: '详情', dataIndex: 'detail', ellipsis: true },
  ]
  return (
    <>
      {signStats && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col xs={12} sm={6}><Card><Statistic title="今日成功" value={signStats.today_success} suffix="次" valueStyle={{ color: '#52c41a', fontSize: 20 }} /></Card></Col>
          <Col xs={12} sm={6}><Card><Statistic title="今日失败" value={signStats.today_fail} suffix="次" valueStyle={{ color: '#ff4d4f', fontSize: 20 }} /></Card></Col>
          <Col xs={12} sm={6}><Card><Statistic title="今日需手动" value={signStats.today_manual} suffix="次" valueStyle={{ color: '#faad14', fontSize: 20 }} /></Card></Col>
          <Col xs={12} sm={6}><Card><Statistic title="累计记录" value={signStats.total_records} suffix="条" valueStyle={{ color: '#1677ff', fontSize: 20 }} /></Card></Col>
        </Row>
      )}
      <Space style={{ marginBottom: 16 }} wrap>
        <Text>用户：</Text>
        <Select value={owner} allowClear placeholder="全部用户" style={{ width: 160 }} onChange={setOwner}
          options={(users || []).map(u => ({ value: u.username, label: u.username }))} />
        <Text>结果：</Text>
        <Select value={result} allowClear placeholder="全部结果" style={{ width: 140 }} onChange={setResult}
          options={Object.entries(REC_RESULT).map(([k, v]) => ({ value: k, label: v.label }))} />
      </Space>
      <Table rowKey={(r) => r.acct_id + '-' + r.time + '-' + r.activity} dataSource={records} columns={columns}
        pagination={{ pageSize: 20 }} scroll={{ x: 'max-content' }} />
    </>
  )
}

// ---------- 系统设置 ----------
// ---------- APP 闪屏 ----------
function SplashTab({ splash, refresh, msg }) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const img = Form.useWatch('image_url', form)
  useEffect(() => {
    if (splash) form.setFieldsValue(splash)
  }, [splash, form])
  if (!splash) return <Spin />
  return (
    <Card style={{ maxWidth: 560 }}>
      <Alert style={{ marginBottom: 16 }} type="info" showIcon
        message="APP 启动时展示，到时自动进首页；点击图片可跳转下方配置的链接" />
      <Form form={form} layout="vertical" onFinish={async v => {
        setSaving(true)
        try {
          await api('/api/admin/splash', { method: 'PUT', body: JSON.stringify(v) })
          msg.success('闪屏配置已保存')
          refresh()
        } catch (e) { msg.error(e.message) } finally { setSaving(false) }
      }}>
        <Form.Item name="enabled" label="启用闪屏" valuePropName="checked"
          extra="关闭后 APP 启动不展示闪屏，直接进首页">
          <Switch />
        </Form.Item>
        <Form.Item name="image_url" label="图片链接" rules={[{ required: true, message: '请输入闪屏图片链接' }]}
          extra="建议 1080×1920 竖图，JPG / PNG，小于 500KB；使用 https 外链或图床地址">
          <Input placeholder="https://example.com/splash.png" maxLength={500} />
        </Form.Item>
        <Form.Item name="duration" label="展示秒数" rules={[{ required: true, message: '请输入展示秒数' }]}
          extra="1~10 秒，到时 APP 自动进入首页">
          <InputNumber min={1} max={10} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="jump_url" label="跳转链接"
          extra="点击闪屏图片跳转的地址（活动页 / 公告页等）；留空 = 点击不跳转">
          <Input placeholder="https://xxt.leich.cn/help" maxLength={500} />
        </Form.Item>
        {img ? (
          <div style={{ marginBottom: 16 }}>
            <Text type="secondary">预览：</Text>
            <img src={img} alt="闪屏预览" style={{ maxWidth: 180, borderRadius: 8, marginTop: 8, display: 'block' }} />
          </div>
        ) : null}
        <Button type="primary" htmlType="submit" loading={saving}>保存配置</Button>
      </Form>
    </Card>
  )
}

function SettingsTab({ settings, refresh, msg }) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (settings) form.setFieldsValue(settings)
  }, [settings, form])
  if (!settings) return <Spin />
  return (
    <Card style={{ maxWidth: 560 }}>
      <Form form={form} layout="vertical" onFinish={async v => {
        setSaving(true)
        try {
          await api('/api/admin/settings', { method: 'PUT', body: JSON.stringify(v) })
          msg.success('设置已保存')
          refresh()
        } catch (e) { msg.error(e.message) } finally { setSaving(false) }
      }}>
        <Form.Item name="site_name" label="站点名称" rules={[{ required: true, message: '请输入站点名称' }]}
          extra="显示在页面标题等位置">
          <Input maxLength={20} />
        </Form.Item>
        <Form.Item name="registration_open" label="开放注册" valuePropName="checked"
          extra="关闭后新用户将无法自行注册（已有用户不受影响）">
          <Switch />
        </Form.Item>
        <Form.Item name="email_notify" label="邮件通知总开关" valuePropName="checked"
          extra="关闭后所有签到成功/失败/提醒邮件都不再发送">
          <Switch />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>保存设置</Button>
      </Form>
    </Card>
  )
}

// ---------- 工单 ----------
function TicketsTab({ tickets, filter, setFilter, onOpen, refresh, msg }) {
  const columns = [
    { title: '#', dataIndex: 'id', width: 60 },
    { title: '提交人', dataIndex: 'uid' },
    { title: '标题', dataIndex: 'subject' },
    { title: '类型', dataIndex: 'category', render: c => <Tag>{TICKET_CATEGORY[c]}</Tag> },
    { title: '状态', dataIndex: 'status', render: s => <Tag color={TICKET_STATUS[s].color}>{TICKET_STATUS[s].label}</Tag> },
    { title: '优先级', dataIndex: 'priority', render: p => <Tag>{TICKET_PRIORITY[p]}</Tag> },
    { title: '回复', dataIndex: 'reply_count', render: v => v > 0 ? <Badge count={v} /> : 0 },
    { title: '更新时间', dataIndex: 'updated_at' },
    { title: '操作', render: (_, r) => <Button type="link" onClick={() => onOpen(r)}>查看</Button> },
  ]
  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Text>筛选：</Text>
        <Select value={filter} allowClear placeholder="全部状态" style={{ width: 160 }} onChange={setFilter}
          options={[{ value: '', label: '全部' }, ...Object.entries(TICKET_STATUS).map(([k, v]) => ({ value: k, label: v.label }))]} />
      </Space>
      <Table rowKey="id" dataSource={tickets} columns={columns} pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
    </>
  )
}

// ---------- 工单详情抽屉 ----------
function TicketDrawer({ t, refresh, onClose, msg }) {
  const [reply, setReply] = useState('')
  const [detail, setDetail] = useState(t)
  useEffect(() => { setDetail(t) }, [t])
  const load = async () => { try { const j = await api('/api/admin/tickets/' + t.id); setDetail(j.ticket) } catch (e) { msg.error(e.message) } }
  const send = async () => {
    if (!reply.trim()) return
    await api(`/api/admin/tickets/${t.id}/reply`, { method: 'POST', body: JSON.stringify({ message: reply }) })
    setReply(''); load(); refresh()
  }
  const setStatus = async (status, priority) => {
    await api(`/api/admin/tickets/${t.id}/status`, { method: 'POST', body: JSON.stringify({ status, priority }) })
    load(); refresh()
  }
  const del = async () => { await api(`/api/admin/tickets/${t.id}`, { method: 'DELETE' }); msg.success('已删除'); onClose() }
  if (!detail) return null
  return (
    <div>
      <Space wrap>
        <Select value={detail.status} style={{ width: 120 }} onChange={v => setStatus(v)} options={Object.entries(TICKET_STATUS).map(([k, v]) => ({ value: k, label: v.label }))} />
        <Select value={detail.priority} style={{ width: 120 }} onChange={v => setStatus(detail.status, v)} options={Object.entries(TICKET_PRIORITY).map(([k, v]) => ({ value: k, label: v }))} />
        <Popconfirm title="删除该工单？" onConfirm={del}><Button danger>删除</Button></Popconfirm>
      </Space>
      <Card size="small" style={{ marginTop: 12, background: '#fafafa' }}>
        <div style={{ whiteSpace: 'pre-wrap' }}>{detail.content}</div>
        <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>提交人 {detail.uid} · {detail.created_at}</div>
      </Card>
      <Divider>对话记录</Divider>
      {!detail.replies.length && <Empty description="暂无回复" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      <List dataSource={detail.replies} renderItem={r => (
        <List.Item>
          <List.Item.Meta
            title={<Space>{r.role === 'admin' ? <Tag color="blue">管理员 {r.from}</Tag> : <Tag>{r.from}</Tag>}<Text type="secondary" style={{ fontSize: 12 }}>{r.time}</Text></Space>}
            description={<div style={{ whiteSpace: 'pre-wrap' }}>{r.message}</div>} />
        </List.Item>
      )} />
      <Input.TextArea rows={3} value={reply} onChange={e => setReply(e.target.value)} placeholder="回复用户…" style={{ marginTop: 12 }} />
      <Button type="primary" block style={{ marginTop: 8 }} onClick={send}>发送回复</Button>
    </div>
  )
}

// ---------- 日志 ----------
function LogsTab({ logs }) {
  const color = { info: '#1677ff', warn: '#faad14', error: '#ff4d4f', alert: '#fa541c', debug: '#999' }
  if (!logs.length) return <Empty description="暂无日志" style={{ marginTop: 60 }} />
  return (
    <Card>
      <List dataSource={[...logs].reverse()} renderItem={l => (
        <List.Item>
          <Space>
            <Text type="secondary" style={{ fontSize: 12, width: 70 }}>{l.time}</Text>
            <Text style={{ color: color[l.level] || '#333', width: 48, fontSize: 12 }}>{l.level}</Text>
            {l.uid && <Tag>{l.uid}</Tag>}
            <Text>{l.msg}</Text>
          </Space>
        </List.Item>
      )} />
    </Card>
  )
}

// ---------- 新建/编辑用户表单 ----------
function UserForm({ uf, editing, onCreated }) {
  const [form] = Form.useForm()
  useEffect(() => { uf.current = form }, [form])
  useEffect(() => {
    if (editing) form.setFieldsValue({ email: editing.email || '', role: editing.role })
    else form.resetFields()
  }, [editing, form])
  return (
    <Form form={form} layout="vertical" onFinish={async v => {
      if (editing) {
        const body = {}
        if (v.email !== undefined) body.email = v.email || ''
        if (v.password) body.password = v.password
        if (v.role) body.role = v.role
        await api(`/api/admin/users/${editing.username}`, { method: 'PUT', body: JSON.stringify(body) })
      } else {
        await api('/api/admin/users', { method: 'POST', body: JSON.stringify(v) })
      }
      onCreated && onCreated()
    }} initialValues={{ role: 'user' }}>
      {!editing && <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}><Input placeholder="2-32 位字母数字" /></Form.Item>}
      {editing && <Form.Item label="用户名"><Input value={editing.username} disabled /></Form.Item>}
      <Form.Item name="password" label={editing ? '新密码（不修改请留空）' : '密码'}
        rules={editing ? [{ min: 6, message: '至少 6 位' }] : [{ required: true, message: '请输入密码' }]}>
        <Input.Password placeholder={editing ? '留空表示不修改' : ''} />
      </Form.Item>
      <Form.Item name="email" label="QQ邮箱" rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
        <Input placeholder="用于接收签到通知，如 123456@qq.com" />
      </Form.Item>
      <Form.Item name="role" label="角色">
        <Select options={[{ value: 'user', label: '普通用户' }, { value: 'admin', label: '管理员' }]} />
      </Form.Item>
    </Form>
  )
}

// ---------- 公告管理 ----------
const ANNO_TYPE = { info: { label: '通知(蓝)', color: 'blue' }, success: { label: '公告(绿)', color: 'green' }, warning: { label: '提示(橙)', color: 'orange' }, error: { label: '重要(红)', color: 'red' } }

function AnnouncementsTab({ announcements, refresh, onEdit, msg }) {
  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '类型', dataIndex: 'type', render: t => <Tag color={ANNO_TYPE[t]?.color}>{ANNO_TYPE[t]?.label || t}</Tag> },
    { title: '标题', dataIndex: 'title' },
    { title: '内容', dataIndex: 'content', ellipsis: true },
    { title: '状态', dataIndex: 'enabled', render: (v, r) => <Switch checked={v} onChange={async nv => { await api(`/api/admin/announcements/${r.id}`, { method: 'PUT', body: JSON.stringify({ enabled: nv }) }); refresh() }} /> },
    { title: '更新时间', dataIndex: 'updated_at' },
    { title: '操作', render: (_, r) => <Space>
      <Button size="small" onClick={() => onEdit(r)}>编辑</Button>
      <Popconfirm title="删除该公告？" onConfirm={async () => { await api(`/api/admin/announcements/${r.id}`, { method: 'DELETE' }); msg.success('已删除'); refresh() }}><Button danger size="small">删除</Button></Popconfirm>
    </Space> },
  ]
  return <Table rowKey="id" dataSource={announcements} columns={columns} pagination={false} scroll={{ x: 'max-content' }} />
}

function AnnouncementForm({ af, editing, onSaved }) {
  const [form] = Form.useForm()
  useEffect(() => { af.current = form }, [form])
  useEffect(() => {
    if (editing) form.setFieldsValue({ title: editing.title, content: editing.content, type: editing.type, enabled: editing.enabled })
    else form.resetFields()
  }, [editing, form])
  const submit = async () => {
    const v = await form.validateFields()
    if (editing) await api(`/api/admin/announcements/${editing.id}`, { method: 'PUT', body: JSON.stringify(v) })
    else await api('/api/admin/announcements', { method: 'POST', body: JSON.stringify(v) })
    onSaved && onSaved()
  }
  return (
    <Form form={form} layout="vertical" onFinish={submit} initialValues={{ type: 'info', enabled: true }}>
      <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
        <Input placeholder="一句话标题" maxLength={50} />
      </Form.Item>
      <Form.Item name="type" label="类型" rules={[{ required: true }]}>
        <Select options={Object.entries(ANNO_TYPE).map(([k, v]) => ({ value: k, label: v.label }))} />
      </Form.Item>
      <Form.Item name="content" label="内容" rules={[{ required: true, message: '请输入内容' }]}>
        <Input.TextArea rows={4} placeholder="公告正文" />
      </Form.Item>
      <Form.Item name="enabled" label="立即展示" valuePropName="checked">
        <Switch />
      </Form.Item>
    </Form>
  )
}

// ---------- APP 版本管理 ----------
// ---------- 邮件群发 ----------
function EmailTab({ users, msg, isMobile }) {
  const [templates, setTemplates] = useState([])
  const [tplId, setTplId] = useState('')
  const [subject, setSubject] = useState('')
  const [content, setContent] = useState('')
  const [toMode, setToMode] = useState('all')
  const [selected, setSelected] = useState([])
  const [task, setTask] = useState(null)
  const [logs, setLogs] = useState([])
  const pollRef = useRef(null)

  const loadLogs = useCallback(async () => {
    try { setLogs((await api('/api/admin/email/logs')).logs || []) } catch (e) {}
  }, [])

  useEffect(() => {
    (async () => {
      try {
        const j = await api('/api/admin/email/templates')
        const tpls = j.templates || []
        setTemplates(tpls)
        const first = tpls.find(t => t.id !== 'custom') || tpls[0]
        if (first) { setTplId(first.id); setSubject(first.subject); setContent(first.content) }
      } catch (e) {}
    })()
    loadLogs()
  }, [loadLogs])

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const applyTemplate = (id) => {
    setTplId(id)
    const t = templates.find(x => x.id === id)
    if (t) { setSubject(t.subject); setContent(t.content) }
  }

  const validUsers = (users || []).filter(u => (u.email || '').trim() && !u.disabled)
  const recipientCount = toMode === 'all' ? validUsers.length : selected.length

  const send = async () => {
    if (!subject.trim()) return msg.error('请填写邮件主题')
    if (!content.trim()) return msg.error('请填写邮件内容')
    if (toMode === 'users' && selected.length === 0) return msg.error('请选择收件用户')
    try {
      const j = await api('/api/admin/email/send', {
        method: 'POST',
        body: JSON.stringify({ to_mode: toMode, usernames: selected, subject, content }),
      })
      msg.success(`已开始发送，共 ${j.total} 人，可在下方查看进度`)
      setTask({ id: j.task_id, total: j.total, done: 0, ok: 0, fail: 0, status: 'running', detail: [] })
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(async () => {
        try {
          const t = (await api(`/api/admin/email/task/${j.task_id}`)).task
          setTask(t)
          if (t.status === 'done') {
            clearInterval(pollRef.current); pollRef.current = null
            msg.success(`发送完成：成功 ${t.ok} 人，失败 ${t.fail} 人`)
            loadLogs()
          }
        } catch (e) {
          clearInterval(pollRef.current); pollRef.current = null
        }
      }, 1500)
    } catch (e) { msg.error(e.message) }
  }

  const logColumns = [
    { title: '时间', dataIndex: 'created_at', width: 150 },
    { title: '主题', dataIndex: 'subject', ellipsis: true },
    { title: '范围', dataIndex: 'to_mode', width: 90, render: v => <Tag color={v === 'all' ? 'blue' : 'default'}>{v === 'all' ? '全部用户' : '指定用户'}</Tag> },
    { title: '收件', dataIndex: 'to_count', width: 60 },
    { title: '成功', dataIndex: 'ok_count', width: 60, render: v => <span style={{ color: '#52c41a' }}>{v}</span> },
    { title: '失败', dataIndex: 'fail_count', width: 60, render: v => <span style={{ color: v ? '#ff4d4f' : undefined }}>{v}</span> },
    { title: '发送者', dataIndex: 'sender', width: 110 },
    { title: '详情', dataIndex: 'detail', ellipsis: true, render: v => v || '-' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 1080 }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card size="small" title={<Space><MailOutlined />第一步：选择模板</Space>}>
            <Space wrap>
              {templates.map(t => (
                <Button key={t.id} type={tplId === t.id ? 'primary' : 'default'} onClick={() => applyTemplate(t.id)}>
                  {t.name}
                </Button>
              ))}
            </Space>
            <div style={{ marginTop: 8 }}><Text type="secondary" style={{ fontSize: 12 }}>选择模板会自动填充主题与正文，可再手动修改</Text></div>
          </Card>

          <Card size="small" title={<Space>第二步：编辑内容</Space>}>
            <div style={{ marginBottom: 8 }}>
              <Text type="secondary">邮件主题</Text>
              <Input value={subject} onChange={e => setSubject(e.target.value)} placeholder="邮件主题" maxLength={120} style={{ marginTop: 4 }} />
            </div>
            <div>
              <Text type="secondary">邮件正文（纯文本，换行分段）</Text>
              <Input.TextArea value={content} onChange={e => setContent(e.target.value)}
                rows={10} placeholder="邮件正文" style={{ marginTop: 4 }} />
            </div>
          </Card>

          <Card size="small" title={<Space>第三步：选择收件人</Space>}>
            <Radio.Group value={toMode} onChange={e => { setToMode(e.target.value); setSelected([]) }} style={{ marginBottom: 12 }}>
              <Radio value="all">全部用户（{validUsers.length} 个有效邮箱）</Radio>
              <Radio value="users">指定用户</Radio>
            </Radio.Group>
            {toMode === 'users' && (
              <Select
                mode="multiple" allowClear showSearch optionFilterProp="label"
                placeholder="搜索并选择用户（username / 邮箱）"
                style={{ width: '100%' }}
                value={selected}
                onChange={setSelected}
                options={validUsers.map(u => ({ value: u.username, label: `${u.username}${u.email ? ` (${u.email})` : ''}` }))}
              />
            )}
            <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <Popconfirm
                title={`确认发送给 ${recipientCount} 人？`}
                description="邮件将真实发送到对方邮箱，并同步生成站内消息"
                onConfirm={send} okText="确认发送" cancelText="取消">
                <Button type="primary" icon={<MailOutlined />} disabled={task && task.status === 'running'}>
                  发送邮件（{recipientCount} 人）
                </Button>
              </Popconfirm>
              {task && task.status === 'running' && (
                <span><Spin size="small" style={{ marginRight: 8 }} />正在发送 {task.done}/{task.total}…</span>
              )}
            </div>
            {task && task.status === 'done' && (
              <Alert style={{ marginTop: 12 }} type={task.fail ? 'warning' : 'success'} showIcon
                message={`发送完成：成功 ${task.ok} 人，失败 ${task.fail} 人`}
                description={task.detail && task.detail.length ? task.detail.join('；') : null} />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card size="small" title="邮件预览" style={{ position: 'sticky', top: 24 }}>
            <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, overflow: 'hidden' }}>
              <div style={{ background: 'linear-gradient(135deg,#e7452a,#ff7a45)', padding: '16px 20px' }}>
                <div style={{ color: '#fff', fontWeight: 600 }}>马上签 · 系统通知</div>
                <div style={{ color: 'rgba(255,255,255,.85)', fontSize: 12, marginTop: 2 }}>超星学习通自动签到</div>
              </div>
              <div style={{ padding: '20px' }}>
                <div style={{ fontWeight: 600, fontSize: 16, color: '#1f2329', marginBottom: 12 }}>{subject || '（邮件主题）'}</div>
                {content ? content.split('\n').map((line, i) => (
                  <div key={i} style={{ fontSize: 13, lineHeight: 1.9, color: '#4a4f59', minHeight: line.trim() ? undefined : 12 }}>{line || '\u00a0'}</div>
                )) : <Text type="secondary">（正文为空）</Text>}
              </div>
              <div style={{ padding: '12px 20px', background: '#fafbfc', borderTop: '1px solid #f0f0f0', fontSize: 11, color: '#9aa0ab' }}>
                本邮件由系统自动发送，请勿直接回复。
              </div>
            </div>
          </Card>
        </Col>
      </Row>

      <Card size="small" title={<Space><HistoryOutlined />发送历史</Space>} extra={<Button size="small" icon={<ReloadOutlined />} onClick={loadLogs}>刷新</Button>}>
        <Table rowKey="id" dataSource={logs} columns={logColumns} pagination={false} size="small" scroll={{ x: 'max-content' }} />
      </Card>
    </div>
  )
}

function AppReleasesTab({ releases, refresh, onEdit, msg }) {
  const columns = [
    { title: 'ID', dataIndex: 'id', width: 56 },
    {
      title: '版本', dataIndex: 'version_name',
      render: (v, r) => <Space><Tag color="blue">v{v}</Tag><Text type="secondary" style={{ fontSize: 12 }}>code {r.version_code}</Text></Space>,
    },
    {
      title: '下载地址', dataIndex: 'apk_url', ellipsis: true,
      render: v => v ? <a href={v} target="_blank" rel="noreferrer">{v}</a> : <Text type="secondary">未填写</Text>,
    },
    {
      title: '更新日志', dataIndex: 'update_log', ellipsis: true,
      render: v => v || <Text type="secondary">-</Text>,
    },
    {
      title: '强制更新', dataIndex: 'force_update', width: 90,
      render: (v, r) => <Switch checked={v} onChange={async nv => { await api(`/api/admin/app-releases/${r.id}`, { method: 'PUT', body: JSON.stringify({ force_update: nv }) }); refresh() }} />,
    },
    {
      title: '最低支持', dataIndex: 'min_supported_code', width: 90,
      render: v => v > 0 ? `code ${v}` : <Text type="secondary">不限</Text>,
    },
    {
      title: '启用', dataIndex: 'enabled', width: 70,
      render: (v, r) => <Switch checked={v} onChange={async nv => { await api(`/api/admin/app-releases/${r.id}`, { method: 'PUT', body: JSON.stringify({ enabled: nv }) }); refresh() }} />,
    },
    { title: '发布时间', dataIndex: 'created_at' },
    {
      title: '操作', width: 110, render: (_, r) => <Space>
        <Button size="small" onClick={() => onEdit(r)}>编辑</Button>
        <Popconfirm title={`删除版本 ${r.version_name}？`} onConfirm={async () => {
          await api(`/api/admin/app-releases/${r.id}`, { method: 'DELETE' }); msg.success('已删除'); refresh()
        }}><Button danger size="small">删除</Button></Popconfirm>
      </Space>,
    },
  ]
  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="APP 启动时会请求 GET /api/app/version 检测更新：返回启用中 version_code 最大的版本作为最新版；勾选「强制更新」或用户版本低于「最低支持」时，APP 将必须升级。" />
      <Table rowKey="id" dataSource={releases} columns={columns} pagination={false} scroll={{ x: 'max-content' }} />
    </>
  )
}

function AppReleaseForm({ rf, editing, onSaved }) {
  const [form] = Form.useForm()
  useEffect(() => { rf.current = form }, [form])
  useEffect(() => {
    if (editing) form.setFieldsValue({
      version_name: editing.version_name, apk_url: editing.apk_url || '',
      update_log: editing.update_log || '', force_update: editing.force_update,
      min_supported_code: editing.min_supported_code || 0, enabled: editing.enabled,
    })
    else form.resetFields()
  }, [editing, form])
  const submit = async () => {
    const v = await form.validateFields()
    if (editing) await api(`/api/admin/app-releases/${editing.id}`, { method: 'PUT', body: JSON.stringify(v) })
    else await api('/api/admin/app-releases', { method: 'POST', body: JSON.stringify(v) })
    onSaved && onSaved()
  }
  return (
    <Form form={form} layout="vertical" onFinish={submit}
      initialValues={{ force_update: false, min_supported_code: 0, enabled: true }}>
      <Form.Item name="version_name" label="版本号" rules={[
        { required: true, message: '请输入版本号' },
        { pattern: /^\d+(\.\d+){1,2}$/, message: '格式应为 x.y 或 x.y.z，如 1.0.0' },
      ]} extra="展示给用户的版本号，如 1.0.0">
        <Input placeholder="1.0.0" disabled={!!editing} />
      </Form.Item>
      <Form.Item name="version_code" label="version_code（版本序号）" rules={[
        { required: true, message: '请输入版本序号' },
        { pattern: /^\d+$/, message: '必须是非负整数' },
      ]} extra="整数，每次发版必须递增且不能重复，用于判断是否有新版本">
        <Input placeholder="1" disabled={!!editing} />
      </Form.Item>
      <Form.Item name="apk_url" label="APK 下载地址" rules={[{ type: 'url', message: '请输入正确的链接' }]}
        extra="安装包直链（http/https），发布后网站主页的「下载 APP」按钮将指向此地址">
        <Input placeholder="https://example.com/mashangqian-1.0.0.apk" />
      </Form.Item>
      <Form.Item name="update_log" label="更新日志" extra="将展示在网站主页版本信息处">
        <Input.TextArea rows={3} placeholder="本次更新内容，如：修复签到通知延迟问题" />
      </Form.Item>
      <Form.Item name="force_update" label="强制更新" valuePropName="checked"
        extra="开启后，低于此版本的 APP 必须升级才能继续使用">
        <Switch />
      </Form.Item>
      <Form.Item name="min_supported_code" label="最低支持 version_code" rules={[{ pattern: /^\d+$/, message: '必须是非负整数' }]}
        extra="低于该序号的旧版本也必须升级，0 表示不限">
        <Input placeholder="0" />
      </Form.Item>
      <Form.Item name="enabled" label="启用该版本" valuePropName="checked"
        extra="关闭后该版本不再作为最新版被检测到（用于下线有问题的版本）">
        <Switch />
      </Form.Item>
    </Form>
  )
}
