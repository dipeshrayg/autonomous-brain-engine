/**
 * executive.js — CEO + CSO meta-watchdog (Node port of executive.py).
 * Reads memory_log.json, asks the LLM for a verdict + directives, appends the
 * review to memory and mirrors it to Supabase. Never halts a build.
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { callWithFallback, AllModelsFailed } from './roles.js'
import { syncReview } from './supabaseSync.js'

const MEMORY_PATH = process.env.MEMORY_PATH || 'memory_log.json'
const REVIEW_WINDOW = 8

const CEO_SYSTEM = `You are the CEO of an autonomous AI software-creation system. You are visionary, high-risk-tolerant, and impatient with safe, derivative work.

Your job: read the recent shipped projects and refused builds, then issue strict directives for the next project. Push toward unpredictable domains and NEVER demand a project_type that is BANNED or has failed repeatedly — the goal is to SHIP. A working project in a safe type beats another failed attempt.

Output STRICT JSON, no prose, no fences:
{
  "verdict": "thriving" | "acceptable" | "drifting" | "alarming",
  "summary": "1-2 sentence executive judgement",
  "concerns": ["sharp concerns about the trajectory"],
  "directives": ["3-6 imperative instructions for the next project, each one concrete thing"],
  "praise": ["sparingly, what went well"]
}`

const CSO_SYSTEM = `You are the Chief SCIENCE Officer of an autonomous software-creation system (NOT security). You demand algorithmic depth, mathematical correctness, and genuine novelty. You complement the CEO: where they push domain leaps, you push for depth within the chosen domain.

Output STRICT JSON, no prose, no fences:
{
  "verdict": "thriving" | "acceptable" | "drifting" | "alarming",
  "summary": "1-2 sentences",
  "concerns": ["scientific / algorithmic concerns"],
  "directives": ["specific algorithmic / scientific demands"],
  "praise": []
}`

function loadMemory() {
  if (!existsSync(MEMORY_PATH)) return { projects: [], ceo_reviews: [], cso_reviews: [], failed_builds: [] }
  return JSON.parse(readFileSync(MEMORY_PATH, 'utf-8'))
}

function saveMemory(mem) {
  writeFileSync(MEMORY_PATH, JSON.stringify(mem, null, 2) + '\n', 'utf-8')
}

function summarizeRecent(projects) {
  if (!projects.length) return '(no projects yet)'
  return projects.map((p) =>
    `- ${p.date || '?'} ${p.name || '?'} c=${p.complexity_score ?? '?'} type=${p.project_type || 'web'} ` +
    `qa=${p.qa_review?.verdict || '-'} pattern=${p.pattern || '?'} domain=${p.domain || '?'}`).join('\n')
}

function summarizeFailures(fails) {
  if (!fails.length) return '(no refused builds in window)'
  return 'REFUSED builds:\n' + fails.map((f) =>
    `- ${f.date || '?'} "${f.plan_name || '?'}" c=${f.plan_complexity ?? '?'} type=${f.project_type || '?'} ` +
    `-> ${f.refusal_stage || '?'}`).join('\n')
}

function parseJson(text) {
  let t = text.trim()
  if (t.startsWith('```')) t = t.replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, '')
  const s = t.indexOf('{'), e = t.lastIndexOf('}')
  if (s < 0 || e < 0) throw new Error(`No JSON object found: ${t.slice(0, 200)}`)
  return JSON.parse(t.slice(s, e + 1))
}

export async function runReview(kind /* 'ceo' | 'cso' */) {
  const table = kind === 'cso' ? 'cso_reviews' : 'ceo_reviews'
  const system = kind === 'cso' ? CSO_SYSTEM : CEO_SYSTEM
  const label = kind.toUpperCase()

  const mem = loadMemory()
  const recent = (mem.projects || []).slice(-REVIEW_WINDOW)
  if (recent.length < 2) { console.log(`Not enough projects (${recent.length}); skipping ${label}.`); return 0 }

  const fails = (mem.failed_builds || []).slice(-REVIEW_WINDOW)
  const user = `Recent ${recent.length} SHIPPED projects (oldest -> newest):\n${summarizeRecent(recent)}\n\n` +
    `${summarizeFailures(fails)}\n\nIssue strict directives for the NEXT project. Specify which project_type to use.`

  let text, meta
  try {
    ({ text, meta } = await callWithFallback(kind, { system, user, maxTokens: 2200, temperature: 0.7 }))
  } catch (e) {
    if (e instanceof AllModelsFailed) { console.error(`${label} review failed: ${e.message}`); return 1 }
    throw e
  }

  let review
  try { review = parseJson(text) }
  catch (e) { console.error(`${label} output not parseable: ${e.message}`); return 1 }

  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
  const record = {
    issued_at: now,
    issued_at_unix: Math.floor(Date.now() / 1000),
    model: meta.model,
    verdict: review.verdict || 'acceptable',
    summary: review.summary || '',
    concerns: review.concerns || [],
    directives: review.directives || [],
    praise: review.praise || [],
    reviewed_project_count: recent.length,
  }
  ;(mem[table] ||= []).push(record)
  saveMemory(mem)
  await syncReview(table, record)

  console.log(`${label} verdict: ${record.verdict} | ${record.directives.length} directives | model=${record.model}`)
  record.directives.forEach((d) => console.log(`  ${label} directive: ${d}`))
  return 0
}
