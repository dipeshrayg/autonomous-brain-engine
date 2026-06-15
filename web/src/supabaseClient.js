import { createClient } from '@supabase/supabase-js'

// The ANON key is safe to ship in the browser — it is bound by Row Level
// Security. Public can read the project showcase; operational tables require a
// logged-in user. Writes are impossible with this key.
const url = import.meta.env.VITE_SUPABASE_URL
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabaseConfigured = Boolean(url && anon)

export const supabase = supabaseConfigured
  ? createClient(url, anon)
  : null
