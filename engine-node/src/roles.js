/**
 * roles.js — multi-provider LLM client (Node port of roles.py).
 *
 * Walks a role's model chain across GitHub Models / Groq / Google until one
 * succeeds. Uses the OpenAI-compatible REST endpoint of each provider via the
 * built-in global fetch (Node 18+), so there is no SDK dependency.
 */

const PROVIDERS = {
  github: { baseUrl: 'https://models.inference.ai.azure.com', envVar: 'GITHUB_TOKEN' },
  groq:   { baseUrl: 'https://api.groq.com/openai/v1',        envVar: 'GROQ_API_KEY' },
  google: { baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai', envVar: 'GOOGLE_AI_KEY' },
}

const MODEL_PROVIDER = {
  'gpt-4o': 'github',
  'gpt-4o-mini': 'github',
  'Phi-4': 'github',
  'llama-3.3-70b-versatile': 'groq',
  'llama-3.1-8b-instant': 'groq',
  'meta-llama/llama-4-scout-17b-16e-instruct': 'groq',
  'gemini-2.0-flash': 'google',
  'gemini-2.0-flash-lite': 'google',
}

const ROLE_CHAIN = {
  ceo: ['gpt-4o', 'llama-3.3-70b-versatile', 'gpt-4o-mini'],
  cso: ['llama-3.3-70b-versatile', 'gpt-4o', 'gpt-4o-mini'],
  architect_candidate_a: ['meta-llama/llama-4-scout-17b-16e-instruct', 'llama-3.3-70b-versatile', 'gpt-4o-mini'],
  architect_candidate_b: ['llama-3.3-70b-versatile', 'meta-llama/llama-4-scout-17b-16e-instruct', 'gpt-4o-mini'],
  architect_judge: ['gpt-4o', 'llama-3.3-70b-versatile'],
  engineer: ['gpt-4o', 'gemini-2.0-flash', 'gpt-4o-mini'],
  reviewer_a: ['llama-3.3-70b-versatile', 'gpt-4o-mini'],
  reviewer_b: ['gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gpt-4o-mini'],
  fixer: ['gpt-4o-mini', 'Phi-4', 'gpt-4o'],
  polisher: ['Phi-4', 'gpt-4o-mini'],
  qa_tester: ['gpt-4o', 'gpt-4o-mini'],
  qa_fixer: ['gemini-2.0-flash', 'gpt-4o'],
}

export class AllModelsFailed extends Error {}

function keyFor(modelId) {
  const provider = PROVIDERS[MODEL_PROVIDER[modelId] || 'github']
  const key = process.env[provider.envVar]
  return key ? { provider, key } : null
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * @returns {Promise<{text: string, meta: object}>}
 */
export async function callWithFallback(role, {
  system, user, maxTokens, temperature = 0.85, jsonMode = true,
  transientAttempts = 2, validator = null,
}) {
  const chain = ROLE_CHAIN[role]
  if (!chain) throw new Error(`Unknown role: ${role}`)
  let lastErr = null

  for (const modelId of chain) {
    const resolved = keyFor(modelId)
    if (!resolved) continue // API key not set — skip silently
    const { provider, key } = resolved
    const providerKey = MODEL_PROVIDER[modelId] || 'github'

    for (let attempt = 1; attempt <= transientAttempts; attempt++) {
      try {
        const body = {
          model: modelId,
          messages: [
            { role: 'system', content: system },
            { role: 'user', content: user },
          ],
          max_tokens: maxTokens,
          temperature,
        }
        if (jsonMode && providerKey !== 'google') {
          body.response_format = { type: 'json_object' }
        }
        const resp = await fetch(`${provider.baseUrl}/chat/completions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
          body: JSON.stringify(body),
        })
        if (!resp.ok) {
          const errText = await resp.text()
          const e = new Error(`HTTP ${resp.status}: ${errText.slice(0, 200)}`)
          e.status = resp.status
          throw e
        }
        const data = await resp.json()
        const text = data.choices?.[0]?.message?.content || ''
        const finish = data.choices?.[0]?.finish_reason

        if (validator) {
          try { validator(text) }
          catch (ve) {
            lastErr = ve
            console.warn(`[role=${role}] model=${modelId} attempt ${attempt} validator rejected (finish=${finish}): ${ve.message}`)
            if (finish === 'length') break
            if (attempt < transientAttempts) { await sleep(1000); continue }
            break
          }
        }
        const meta = {
          role, model: modelId, provider: providerKey, attempt,
          prompt_tokens: data.usage?.prompt_tokens,
          completion_tokens: data.usage?.completion_tokens,
        }
        console.log(`[role=${role}] model=${modelId} attempt=${attempt} OK (in=${meta.prompt_tokens} out=${meta.completion_tokens})`)
        return { text, meta }
      } catch (e) {
        lastErr = e
        const msg = String(e.message || e).slice(0, 280)
        const rateLimited = /429|rate|quota|tokens_limit/i.test(msg)
        const tooLarge = /413|tokens_limit_reached/i.test(msg)
        if (rateLimited || tooLarge) {
          console.warn(`[role=${role}] model=${modelId} attempt ${attempt} failed (${msg.slice(0, 120)}); falling back`)
          break
        }
        if (attempt < transientAttempts) {
          const backoff = 2 ** attempt * 1000
          console.warn(`[role=${role}] model=${modelId} attempt ${attempt} failed; retrying in ${backoff}ms`)
          await sleep(backoff)
          continue
        }
        break
      }
    }
  }
  throw new AllModelsFailed(`role=${role}: every model failed. Last error: ${lastErr?.message || lastErr}`)
}

export { PROVIDERS, MODEL_PROVIDER, ROLE_CHAIN }
