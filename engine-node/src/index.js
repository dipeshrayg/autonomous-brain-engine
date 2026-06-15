#!/usr/bin/env node
/**
 * index.js — CLI entry for the Node engine (parallel build).
 *
 * Currently ported:
 *   node src/index.js ceo   — run the CEO review
 *   node src/index.js cso   — run the CSO science review
 *
 * The full pipeline (architect -> implement -> QA -> publish) is being ported
 * incrementally; until it reaches parity, the Python engine remains the
 * shipping path. See engine-node/README.md for the cutover plan.
 */

import { runReview } from './executive.js'

const cmd = process.argv[2] || 'ceo'

const main = async () => {
  switch (cmd) {
    case 'ceo': return runReview('ceo')
    case 'cso': return runReview('cso')
    default:
      console.error(`Unknown command: ${cmd}. Use: ceo | cso`)
      return 2
  }
}

main().then((code) => process.exit(code || 0)).catch((e) => {
  console.error('Unhandled error:', e)
  // Non-halting parity with the Python engine: never fail the build on engine error.
  process.exit(0)
})
