import { useState, useMemo, useEffect } from 'react'
import { usePhotoStore } from '../stores/photoStore'
import * as api from '../services/api'
import './SubmitPanel.css'

// 与后端 _safe 一致的路径片段清洗
function safe(s) {
  s = (s || '').trim().replace(/[\\/:*?"<>|]/g, '_').replace(/\.\./g, '_')
  return s || '未命名'
}

// 按需加载 ali-oss 浏览器 SDK（仅 OSS 直传模式用到）
function loadOssSdk() {
  if (window.OSS) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://cdn.jsdelivr.net/npm/ali-oss@6.18.1/dist/aliyun-oss-sdk.min.js'
    s.onload = resolve
    s.onerror = () => reject(new Error('加载上传组件失败，请检查网络'))
    document.head.appendChild(s)
  })
}

const LS_KEY = 'intake_server_url'

export default function SubmitPanel() {
  const { photos, selectedIds } = usePhotoStore()

  const [serverUrl, setServerUrl] = useState(localStorage.getItem(LS_KEY) || '')
  const [code, setCode] = useState('')
  const [name, setName] = useState('')             // 摄影师姓名，需与投稿码登记一致
  const [verified, setVerified] = useState(null)   // { name, mode, history }
  const [verifyMsg, setVerifyMsg] = useState('')
  const [license, setLicense] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState('')

  // 展示在画廊里勾选的照片
  const analyzed = useMemo(
    () => photos.filter(p => selectedIds.includes(p.id)),
    [photos, selectedIds]
  )

  const [selected, setSelected] = useState(() => new Set())
  const [labels, setLabels] = useState({})         // id -> content_label
  const [progress, setProgress] = useState({})     // id -> 0..100

  // 进入时默认全选，标注框留空让用户自行填写
  useEffect(() => {
    setSelected(new Set(analyzed.map(p => p.id)))
  }, [analyzed])

  const base = serverUrl.replace(/\/+$/, '')

  function persistUrl(v) {
    setServerUrl(v)
    localStorage.setItem(LS_KEY, v.trim())
  }

  async function verify() {
    setVerified(null); setVerifyMsg('')
    if (!base) { setVerifyMsg('请先填写征稿服务器地址'); return }
    if (!code.trim() || !name.trim()) return
    try {
      const fd = new FormData(); fd.append('code', code.trim())
      const r = await fetch(base + '/api/intake/verify', { method: 'POST', body: fd })
      if (!r.ok) throw new Error('投稿码无效')
      const d = await r.json()
      // 姓名与投稿码登记的不一致 → 拒绝
      if (name.trim() !== (d.name || '').trim()) {
        setVerifyMsg('✗ 姓名与投稿码不符'); return
      }
      const cfg = await fetch(base + '/api/intake/oss-config').then(x => x.json())
      setVerified({ name: d.name, bookTitle: d.book_title, history: d.history || [], mode: cfg.mode })
      setVerifyMsg('✅ 欢迎您！' + d.name + ' 大师～～')
    } catch (e) {
      setVerifyMsg('✗ ' + (e.message || '校验失败，检查地址与投稿码'))
    }
  }

  function toggle(id) {
    setSelected(prev => {
      const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n
    })
  }

  const selectedList = analyzed.filter(p => selected.has(p.id))
  const canSubmit = verified && selectedList.length > 0 && license && !busy

  async function submit() {
    if (!canSubmit) return
    setBusy(true); setResult('')
    try {
      // 1) 创建会话
      const fd = new FormData(); fd.append('code', code.trim()); fd.append('license_agreed', '1')
      const sid = (await fetch(base + '/api/intake/submit', { method: 'POST', body: fd }).then(r => r.json())).submission_id

      // 2) OSS 模式准备客户端
      let oss = null
      if (verified.mode === 'oss') {
        await loadOssSdk()
        const s = await fetch(base + '/api/intake/sts', { method: 'POST', body: codeForm() }).then(r => r.json())
        oss = {
          prefix: s.prefix,
          client: new window.OSS({
            region: s.region, bucket: s.bucket,
            accessKeyId: s.credentials.AccessKeyId,
            accessKeySecret: s.credentials.AccessKeySecret,
            stsToken: s.credentials.SecurityToken, secure: true,
            refreshSTSToken: async () => {
              const s2 = await fetch(base + '/api/intake/sts', { method: 'POST', body: codeForm() }).then(r => r.json())
              return {
                accessKeyId: s2.credentials.AccessKeyId,
                accessKeySecret: s2.credentials.AccessKeySecret,
                stsToken: s2.credentials.SecurityToken,
              }
            },
          }),
        }
      }

      // 3) 逐张上传（携带本地 AI 索引）
      for (const p of selectedList) {
        const blob = await fetch(api.originalUrl(p.id)).then(r => r.blob())
        const label = (labels[p.id] || '').trim()
        const ai = p.ai || {}
        const meta = {
          photographer: ai.photographer || '', location: ai.location || '',
          category: ai.category || '', description: ai.description || '',
          tags: ai.tags ? JSON.stringify(ai.tags) : '',
        }
        if (oss) {
          const key = oss.prefix + safe(label) + '/' + safe(p.file_name)
          await oss.client.multipartUpload(key, new File([blob], p.file_name), {
            parallel: 4, partSize: 1024 * 1024,
            progress: (pct) => setProgress(pr => ({ ...pr, [p.id]: Math.round(pct * 100) })),
          })
          const rf = new FormData()
          rf.append('submission_id', sid); rf.append('content_label', label)
          rf.append('object_key', key); rf.append('file_name', p.file_name)
          rf.append('file_size', blob.size)
          for (const k in meta) rf.append(k, meta[k])
          await fetch(base + '/api/intake/record', { method: 'POST', body: rf })
        } else {
          const uf = new FormData()
          uf.append('submission_id', sid); uf.append('content_label', label)
          uf.append('file', blob, p.file_name)
          for (const k in meta) uf.append(k, meta[k])
          await fetch(base + '/api/intake/upload', { method: 'POST', body: uf })
        }
        setProgress(pr => ({ ...pr, [p.id]: 100 }))
      }

      // 4) 完成
      const cf = new FormData(); cf.append('submission_id', sid)
      await fetch(base + '/api/intake/complete', { method: 'POST', body: cf })
      setResult('✓ 投稿成功，共 ' + selectedList.length + ' 张')
    } catch (e) {
      setResult('✗ ' + (e.message || '提交失败，请重试'))
    } finally {
      setBusy(false)
    }
  }

  function codeForm() { const f = new FormData(); f.append('code', code.trim()); return f }

  return (
    <div className="submit-panel">
      <h2>提交投稿</h2>
      <p className="sp-hint">把本地已 AI 标注的照片提交到征稿服务器。摄影师/地点/类别等索引会一并上传，方便后期管理。</p>

      <div className="sp-row">
        <label>征稿服务器地址</label>
        <input value={serverUrl} onChange={e => persistUrl(e.target.value)}
          placeholder="如 https://你的域名 或 http://127.0.0.1:8000" style={{ flex: 1 }} />
      </div>
      <div className="sp-row">
        <label>投稿码</label>
        <input value={code} onChange={e => setCode(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && verify()} placeholder="如 A01" style={{ width: 120 }} />
        <input value={name} onChange={e => setName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && verify()} onBlur={verify}
          placeholder="摄影师姓名" style={{ width: 150 }} />
        <span className={'sp-msg ' + (verified ? 'ok' : 'err')}>{verifyMsg}</span>
      </div>

      {verified && verified.history.length > 0 && (
        <div className="sp-history">
          <b>该投稿码历史：</b>
          {verified.history.map((h, i) => <span key={i} className="sp-tag">{h.label} {h.count}张</span>)}
        </div>
      )}

      <div className="sp-toolbar">
        <span>已选 {selectedList.length} / {analyzed.length} 张</span>
        <button onClick={() => setSelected(new Set(analyzed.map(p => p.id)))}>全选</button>
        <button onClick={() => setSelected(new Set())}>清空</button>
      </div>

      <div className="sp-list">
        {analyzed.length === 0 && <p className="sp-empty">没有选中的照片。请回到画廊勾选要投稿的照片，再点「确认投稿」。</p>}
        {analyzed.map(p => (
          <div key={p.id} className={'sp-item' + (selected.has(p.id) ? ' on' : '')}>
            <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} />
            <img src={`/api/thumbnails/${p.id}`} alt={p.file_name} />
            <div className="sp-meta">
              <div className="sp-fn">{p.file_name}</div>
              <div className="sp-ai">
                {p.ai?.photographer && <span>📷 {p.ai.photographer}</span>}
                {p.ai?.location && <span>📍 {p.ai.location}</span>}
                {p.ai?.category && <span>🏷 {p.ai.category}</span>}
              </div>
            </div>
            <input className="sp-label" value={labels[p.id] || ''} placeholder="特别标注，非必填"
              onChange={e => setLabels(l => ({ ...l, [p.id]: e.target.value }))} />
            {progress[p.id] > 0 && <span className="sp-pct">{progress[p.id]}%</span>}
          </div>
        ))}
      </div>

      <label className="sp-agree">
        <input type="checkbox" checked={license} onChange={e => setLicense(e.target.checked)} />
        <span>本人确认拥有所提交照片的完整著作权，并预授权出版方仅在本书及相关宣传中使用。授权时间将被记录存档。正式授权以正式授权书为准。</span>
      </label>


      <button className="sp-submit" disabled={!canSubmit} onClick={submit}>
        {busy ? '上传中…' : `提交本次投稿（${selectedList.length} 张）`}
      </button>
      {result && <p className={'sp-result ' + (result.startsWith('✓') ? 'ok' : 'err')}>{result}</p>}
    </div>
  )
}
