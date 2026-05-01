# Security Policy

The Autonomous Brain is an automated software-creation pipeline that designs, tests, and publishes new code every day on GitHub-hosted infrastructure. Because it operates without human review on every cycle, security is treated as a first-class property of the system itself. We appreciate the help of the security research community in keeping it safe, predictable, and trustworthy for the people who run their own forks of it.

This policy describes which components are supported, how to report a vulnerability, what to expect from us after you do, and which protections are already in place. Please read it before submitting a report.

## Supported Versions

The project follows a continuous-deployment model — there are no semantic releases or long-lived version branches. The most recent commit on `main` is always the canonical, supported state of the system, and security fixes ship as ordinary commits.

| Component                                              | Supported          | Notes                                                                                                              |
| ------------------------------------------------------ | ------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `main` branch (orchestrator, prompts, workflows)       | :white_check_mark: | Actively maintained. All security fixes land here.                                                                 |
| Workflow files (`.github/workflows/*.yml`)             | :white_check_mark: | Including `daily_build.yml`, `watchdog.yml`, and any future scheduling or monitoring workflows.                    |
| Pipeline modules (`brain.py`, `pipeline.py`, `verifier.py`, `dashboard.py`) | :white_check_mark: | The orchestration core.                                                                                            |
| Per-day generated repositories (`YYYY-MM-DD-<name>`)   | :large_orange_diamond: | Best-effort. These are immutable snapshots produced by the pipeline; we do not back-port fixes, but critical findings will result in repository deletion or archival. |
| GitHub Pages live demos                                | :large_orange_diamond: | Best-effort, same as above. Reports of XSS, CSP gaps, prototype pollution, or library misuse are welcomed.        |
| Forks, mirrors, or unofficial copies                   | :x:                | Out of scope. Please report to the maintainers of those forks.                                                     |
| Old commits / orphaned auto-generated repos            | :x:                | If you find an issue in a snapshot we have moved past, the fix is on `main` or the repo will be removed.           |

## Reporting a Vulnerability

**The preferred channel is GitHub's private Security Advisory form:**

➡ **[Report a vulnerability privately](https://github.com/dipeshrayg/autonomous-brain/security/advisories/new)**

Please **do not** open a public issue, pull request, or discussion thread for vulnerability reports — doing so exposes other users before a fix is available. If you are unable to access the Security Advisory form, open an issue titled exactly *"Security contact requested"* with no technical details, and we will respond with a private channel within one business day.

### What to include in a report

A high-quality report makes triage faster and your work more impactful. Please include:

1. A clear, single-sentence summary of the vulnerability.
2. The affected component, file path, and the commit hash or tag you tested against.
3. A minimal reproduction recipe — exact steps, payload, and expected versus actual behaviour.
4. An impact statement — what an attacker can achieve, and under what preconditions.
5. (Optional but appreciated) a suggested fix or mitigation, and any references to similar prior art.
6. Whether you wish to be publicly credited, and the name and optional URL you would like used.

### Response timeline

Once we receive your report you can expect the following. These are targets we hold ourselves to, not estimates — if we will miss one of them, we will tell you in advance and explain why.

| Phase                | Target                            | What happens                                                                                                  |
| -------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **Acknowledgement**  | Within **48 hours**               | We confirm receipt and assign a tracking identifier.                                                          |
| **Initial triage**   | Within **7 days**                 | We reproduce the issue, assess severity, and tell you whether we accept the report.                           |
| **Status updates**   | At least every **7 days**         | While the report is open, you receive a written update at least weekly.                                       |
| **Fix and disclosure** | **Severity-dependent** (below)  | A coordinated fix lands on `main`. A GitHub Security Advisory is published, with credit if you wished it.     |

### Severity guidance

| Severity              | Examples                                                                                                                                           | Target time-to-fix  |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| **Critical**          | Exfiltration of `GH_PAT` or any other secret; arbitrary code execution on the runner; account takeover of the maintainer.                          | **Within 7 days**   |
| **High**              | Authenticated bypass of the safety gates; injection that causes the pipeline to push attacker-controlled code into a victim's repository or Pages site. | **Within 30 days**  |
| **Medium**            | Stored or reflected XSS in a generated demo; prompt-injection that materially alters a single project's contents but does not escape the sandbox.   | **Within 60 days**  |
| **Low / informational** | Hardening recommendations and best-practice deviations with no demonstrable impact.                                                              | Best effort         |

### Coordinated disclosure

We follow a default 90-day coordinated-disclosure window measured from the date we acknowledge your report. The advisory will be published on the earlier of (a) the day the fix lands on `main` and is deployed, or (b) the 90-day mark, unless we have agreed an extension with you in writing. If a vulnerability is being actively exploited in the wild we may shorten the window in coordination with you.

## Out of Scope

The following are not considered vulnerabilities under this policy:

- **GitHub platform issues**, including the Actions runner, Pages infrastructure, GitHub Models endpoint, and the Security Advisory system itself. Report these to GitHub: https://bounty.github.com.
- **Vulnerabilities in third-party CDN libraries** (e.g. Chart.js, p5.js, d3, chroma.js) loaded by generated projects. Please report upstream; we will pin or replace affected versions when an advisory is published.
- **Educational content of generated projects.** By design, projects may demonstrate cryptography, network behaviour, security concepts, or financial models. The system prompt forbids active malware, credential theft, exfiltration, exploits against systems without consent, and detection-evasion tooling. If you find generated code that crosses one of those lines, that is a bug — please report it.
- **Self-XSS** requiring the victim to paste attacker-supplied input into their own developer console.
- **Missing security headers** that GitHub Pages does not allow user-side configuration of (HSTS preloading, COEP/COOP, etc.). Please report upstream.
- **Rate-limit abuse of the LLM API by an attacker who already controls the repository.** A user with `Actions: write` on the repository is already trusted; this is not a privilege boundary the system attempts to defend.
- **Reports generated solely from automated scanners** with no demonstrated impact.
- **Social-engineering, phishing, or physical attacks** against the maintainer.

## Safe Harbor

We support good-faith security research. If you make a good-faith effort to comply with this policy while investigating and reporting a vulnerability, we will:

- not initiate or support legal action against you,
- not ask GitHub or any third party to take action against you,
- treat your report as confidential and not share it without your consent.

Good faith means, in summary:

- You give us a reasonable opportunity to fix the issue before public disclosure.
- You do not access, modify, exfiltrate, or destroy data belonging to others.
- You do not degrade availability of the system for legitimate users.
- You do not perform social engineering, physical attacks, or attacks on third-party services.
- You test only against your own fork or against components you are authorised to test.

This safe-harbor commitment does not authorise illegal acts and grants no rights beyond those expressly described.

## Existing Protections

So that reports can be specific about what they bypass, the following controls are already implemented and verified in CI:

- **Hard advancement gates** in `pipeline.py` reject any plan that does not increase complexity, introduce novel concepts, or rotate pattern + domain away from recent history.
- **Prompt-level refusal of weaponised output.** The system prompt forbids ransomware, credential stealers, persistence implants, sandbox-escape exploits, network worms, exfiltration, and detection-evasion tooling. Security-themed projects are constrained to educational and diagnostic forms.
- **Headless-browser verification.** Every project is loaded in a real Chromium instance via Playwright before publish; console errors, page errors, dangling local file references, blank canvases, and missing user controls are detected mechanically.
- **Pre-publish blocking gate.** `brain.py` refuses to push if any blocking issue remains after the final-verify pass.
- **Polish rollback.** If the polish stage regresses quality compared to the pre-polish snapshot, the polished files are discarded and the pre-polish version is published instead.
- **Idempotency and dispatch caps.** A maximum of 2 projects per UTC date are produced from scheduled runs; the watchdog auto-dispatch is capped at 8 attempts per day to prevent runaway loops.
- **CDN-only external libraries** with pinned versions. The verifier mechanically rejects any HTML or CSS that references a relative file path which does not exist in the workspace.
- **Path-traversal validation.** The pipeline rejects absolute paths, parent-directory segments, symlinks, and references that escape the project workspace.
- **Least-privilege tokens.** The auto-injected `GITHUB_TOKEN` is granted only the permissions required by each workflow (`contents: write`, `models: read`, `actions: write`). Cross-repository creation uses a separate, scoped, fine-grained personal access token stored as the `GH_PAT` secret.
- **Noise filtering.** Known environmental artefacts (WebGL software-renderer warnings, autoplay policy hints, favicon 404s) are filtered from the verifier so they cannot be confused with real findings.

## Recognition

If your report leads to a fix or a meaningful hardening change, and you wish to be acknowledged, we will:

- credit you in the GitHub Security Advisory,
- add your name and optional URL to a `SECURITY-CREDITS.md` file in this repository.

This is a personal project and there is no monetary bug bounty. Your work is genuinely appreciated regardless of compensation.

---

*Last updated: 2026-05-01. Policy is versioned via the commit history of this file; the most recent commit is the authoritative version.*
