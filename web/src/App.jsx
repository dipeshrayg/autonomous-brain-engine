import { useEffect, useState } from 'react'
import { supabase, supabaseConfigured } from './supabaseClient.js'

/* ───────────────────────── helpers ───────────────────────── */
const fmtDate = (s) => (s ? new Date(s).toLocaleDateString(undefined,
  { year: 'numeric', month: 'short', day: 'numeric' }) : '—')

const verdictClass = (v) => ({
  shippable: 'badge ok', partially_usable: 'badge warn', non_functional: 'badge bad',
  thriving: 'badge ok', acceptable: 'badge ok', drifting: 'badge warn', alarming: 'badge bad',
}[v] || 'badge')

/* ───────────────────────── app ───────────────────────── */
export default function App() {
  const [session, setSession] = useState(null)
  const [stats, setStats] = useState(null)
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!supabaseConfigured) { setLoading(false); return }
    supabase.auth.getSession().then(({ data }) => setSession(data.session))
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s))
    return () => sub.subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (!supabaseConfigured) return
    ;(async () => {
      const [{ data: st }, { data: pj }] = await Promise.all([
        supabase.from('public_stats').select('*').single(),
        supabase.from('projects').select('*').order('completed_at', { ascending: false }),
      ])
      setStats(st); setProjects(pj || []); setLoading(false)
    })()
  }, [])

  if (!supabaseConfigured) return <ConfigNotice />

  return (
    <div className="page">
      <Header />
      <StatBar stats={stats} projectCount={projects.length} />
      <AuthBar session={session} />
      <section>
        <h2 className="section-title">Shipped projects <span className="count">{projects.length}</span></h2>
        {loading ? <Spinner /> : <ProjectGrid projects={projects} />}
      </section>
      {session && <OpsPanels />}
      <Footer authed={!!session} />
    </div>
  )
}

/* ───────────────────────── header & stats ───────────────────────── */
function Header() {
  return (
    <header className="hero">
      <div className="hero-badge">● LIVE · autonomous · zero-cost</div>
      <h1>Autonomous Brain</h1>
      <p className="tagline">
        An autonomous AI system that designs, builds, quality-tests, and ships live
        software around the clock — for <strong>$0/month</strong>. Every project,
        review, and log line below is served from a real Postgres database with
        enforced row-level security.
      </p>
    </header>
  )
}

function StatBar({ stats, projectCount }) {
  const items = [
    ['Projects shipped', stats?.total_projects ?? projectCount],
    ['Project types', stats?.project_types ?? '—'],
    ['Peak complexity', stats?.peak_complexity ?? '—'],
    ['Concepts explored', stats?.concepts_explored ?? '—'],
    ['Domains explored', stats?.domains_explored ?? '—'],
  ]
  return (
    <div className="statbar">
      {items.map(([label, val]) => (
        <div className="stat" key={label}>
          <div className="stat-num">{val}</div>
          <div className="stat-label">{label}</div>
        </div>
      ))}
    </div>
  )
}

/* ───────────────────────── auth ───────────────────────── */
function AuthBar({ session }) {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const signIn = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    const { error } = await supabase.auth.signInWithOtp({
      email, options: { emailRedirectTo: window.location.href },
    })
    setBusy(false)
    if (error) setErr(error.message); else setSent(true)
  }

  if (session) {
    return (
      <div className="authbar in">
        <span className="dot-ok" /> Signed in as <strong>{session.user.email}</strong>
        <span className="auth-hint">— operational logs unlocked below</span>
        <button className="btn ghost" onClick={() => supabase.auth.signOut()}>Sign out</button>
      </div>
    )
  }
  return (
    <div className="authbar">
      <div className="auth-copy">
        <strong>Board / team access.</strong> The public sees shipped projects.
        Sign in to unlock failure logs, executive reviews, and the raw build stream
        (RLS-gated).
      </div>
      {sent ? (
        <div className="auth-sent">✓ Magic link sent to {email}. Check your inbox.</div>
      ) : (
        <form className="auth-form" onSubmit={signIn}>
          <input type="email" required placeholder="you@org.com" value={email}
                 onChange={(e) => setEmail(e.target.value)} />
          <button className="btn" disabled={busy}>{busy ? 'Sending…' : 'Send magic link'}</button>
        </form>
      )}
      {err && <div className="auth-err">{err}</div>}
    </div>
  )
}

/* ───────────────────────── projects ───────────────────────── */
function ProjectGrid({ projects }) {
  if (!projects.length) return <Empty>No projects yet.</Empty>
  return (
    <div className="grid">
      {projects.map((p) => (
        <article className="card" key={p.id}>
          <div className="card-top">
            <span className="chip">{p.project_type}</span>
            <span className="cx">c{p.complexity_score}</span>
          </div>
          <h3>{p.name}</h3>
          {p.description && <p className="desc">{p.description}</p>}
          <div className="card-meta">
            {p.qa_verdict && <span className={verdictClass(p.qa_verdict)}>{p.qa_verdict.replace('_', ' ')}</span>}
            <span className="muted">{fmtDate(p.completed_at)}</span>
          </div>
          <div className="card-links">
            {p.pages_url && <a className="btn sm" href={p.pages_url} target="_blank" rel="noreferrer">Live ↗</a>}
            {p.repo_url && <a className="btn sm ghost" href={p.repo_url} target="_blank" rel="noreferrer">Code</a>}
          </div>
        </article>
      ))}
    </div>
  )
}

/* ───────────────────────── auth-gated ops ───────────────────────── */
function OpsPanels() {
  const [tab, setTab] = useState('fails')
  const tabs = [
    ['fails', 'Failed builds'],
    ['ceo', 'CEO reviews'],
    ['cso', 'CSO reviews'],
    ['logs', 'Build logs'],
  ]
  return (
    <section className="ops">
      <h2 className="section-title">Operations <span className="lock">🔒 authenticated</span></h2>
      <div className="tabs">
        {tabs.map(([k, label]) => (
          <button key={k} className={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      {tab === 'fails' && <FailTable />}
      {tab === 'ceo' && <ReviewList table="ceo_reviews" />}
      {tab === 'cso' && <ReviewList table="cso_reviews" />}
      {tab === 'logs' && <LogStream />}
    </section>
  )
}

function useRows(table, order, opts = {}) {
  const [rows, setRows] = useState(null)
  useEffect(() => {
    let q = supabase.from(table).select('*').order(order, { ascending: false })
    if (opts.limit) q = q.limit(opts.limit)
    q.then(({ data }) => setRows(data || []))
  }, [table, order])
  return rows
}

function FailTable() {
  const rows = useRows('failed_builds', 'attempted_at', { limit: 100 })
  if (!rows) return <Spinner />
  if (!rows.length) return <Empty>No failed builds.</Empty>
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>When</th><th>Plan</th><th>Type</th><th>Stage</th><th>Verdict</th><th>Reason</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="muted">{fmtDate(r.attempted_at)}</td>
              <td>{r.plan_name}</td>
              <td><span className="chip sm">{r.project_type}</span></td>
              <td className="muted">{r.refusal_stage}</td>
              <td>{r.qa_verdict && <span className={verdictClass(r.qa_verdict)}>{r.qa_verdict.replace('_', ' ')}</span>}</td>
              <td className="reason">{r.refusal_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ReviewList({ table }) {
  const rows = useRows(table, 'issued_at', { limit: 50 })
  if (!rows) return <Spinner />
  if (!rows.length) return <Empty>No reviews.</Empty>
  return (
    <div className="reviews">
      {rows.map((r) => (
        <div className="review" key={r.id}>
          <div className="review-head">
            <span className={verdictClass(r.verdict)}>{r.verdict}</span>
            <span className="muted">{fmtDate(r.issued_at)} · {r.model}</span>
          </div>
          {r.summary && <p>{r.summary}</p>}
          {Array.isArray(r.directives) && r.directives.length > 0 && (
            <ul className="directives">{r.directives.map((d, i) => <li key={i}>{d}</li>)}</ul>
          )}
        </div>
      ))}
    </div>
  )
}

function LogStream() {
  const rows = useRows('build_logs', 'created_at', { limit: 100 })
  if (!rows) return <Spinner />
  if (!rows.length) return <Empty>No log lines yet.</Empty>
  return (
    <div className="logs">
      {rows.map((r) => (
        <div className={`logline ${r.level}`} key={r.id}>
          <span className="ts">{new Date(r.created_at).toLocaleTimeString()}</span>
          <span className={`lvl ${r.level}`}>{r.level}</span>
          {r.stage && <span className="stage">{r.stage}</span>}
          <span className="msg">{r.message}</span>
        </div>
      ))}
    </div>
  )
}

/* ───────────────────────── misc ───────────────────────── */
const Spinner = () => <div className="spinner">Loading…</div>
const Empty = ({ children }) => <div className="empty">{children}</div>

function ConfigNotice() {
  return (
    <div className="page">
      <Header />
      <div className="empty" style={{ marginTop: 40 }}>
        Supabase env not set. Define <code>VITE_SUPABASE_URL</code> and
        <code> VITE_SUPABASE_ANON_KEY</code> (see <code>web/.env.local.example</code>).
      </div>
    </div>
  )
}

function Footer({ authed }) {
  return (
    <footer className="foot">
      <span>Postgres + Row Level Security · GitHub Actions · zero infrastructure cost</span>
      <span className="muted">{authed ? 'authenticated session' : 'public view'}</span>
    </footer>
  )
}
