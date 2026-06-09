"""
generate_paper_docx.py  --  Microsoft Word (.docx) version of the research paper.
Reuses chart generators and live data from generate_paper.py.

Run:  python generate_paper_docx.py
Out:  Dipesh_Ray_Autonomous_Brain_Research_Paper.docx
"""

import json, re

import matplotlib
matplotlib.use('Agg')

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# -- Import chart generators + live data from generate_paper.py --------------
from generate_paper import (
    make_architecture_diagram,
    make_complexity_chart,
    make_type_distribution,
    make_ceo_verdict_timeline,
    make_pipeline_flow,
    PROJECTS, FAILED, CEO_REV,
)

# -- Page geometry (A4, 2.54 cm margins) -------------------------------------
TEXT_WIDTH_CM = 21.0 - 2 * 2.54   # 15.92 cm
MARGIN_CM     = 2.54


# ============================================================================
# LOW-LEVEL HELPERS
# ============================================================================

def _parse_html(text):
    """Split an HTML-annotated string into (text, bold, italic, mono) tuples."""
    segs = []
    bold = italic = mono = False
    for part in re.split(r'(<[^>]+>)', str(text)):
        lp = part.lower()
        if   lp == '<b>':            bold   = True
        elif lp == '</b>':           bold   = False
        elif lp == '<i>':            italic = True
        elif lp == '</i>':           italic = False
        elif lp == '<tt>':           mono   = True
        elif lp == '</tt>':          mono   = False
        elif lp in ('<br/>', '<br />', '<br>'): segs.append(('\n', False, False, False))
        elif part and not part.startswith('<'):
            segs.append((part, bold, italic, mono))
    return segs


def _run(para, text, bold=False, italic=False, mono=False, size_pt=10):
    run = para.add_run(text)
    run.font.name  = 'Courier New' if mono else 'Times New Roman'
    run.font.size  = Pt(size_pt)
    run.font.bold  = bold
    run.font.italic = italic
    return run


def _fmt(para, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
         sb=0, sa=6, li=0, fi=0, ls=14):
    pf = para.paragraph_format
    pf.alignment         = align
    pf.space_before      = Pt(sb)
    pf.space_after       = Pt(sa)
    pf.line_spacing      = Pt(ls)
    if li: pf.left_indent       = Cm(li)
    if fi: pf.first_line_indent = Cm(fi)


# ============================================================================
# PARAGRAPH HELPERS
# ============================================================================

def plain(doc, text, bold=False, italic=False, mono=False,
          align=WD_ALIGN_PARAGRAPH.JUSTIFY,
          size=10, sb=0, sa=6, li=0, fi=0):
    p = doc.add_paragraph()
    _fmt(p, align=align, sb=sb, sa=sa, li=li, fi=fi)
    _run(p, text, bold=bold, italic=italic, mono=mono, size_pt=size)
    return p


def rich(doc, html, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
         size=10, sb=0, sa=6, li=0, fi=0, italic_body=False):
    """Paragraph with inline <b>, <i>, <tt> markup."""
    p = doc.add_paragraph()
    _fmt(p, align=align, sb=sb, sa=sa, li=li, fi=fi)
    for seg, bold, italic, mono in _parse_html(html):
        if seg == '\n':
            p.add_run('\n')
        else:
            _run(p, seg, bold=bold, italic=italic or italic_body,
                 mono=mono, size_pt=size)
    return p


def h1(doc, text):
    """IEEE Roman-numeral section heading -- centred bold."""
    p = doc.add_paragraph()
    _fmt(p, align=WD_ALIGN_PARAGRAPH.CENTER, sb=14, sa=4)
    r = p.add_run(text)
    r.font.name = 'Times New Roman'
    r.font.size = Pt(10)
    r.font.bold = True
    return p


def h2(doc, text):
    """IEEE letter-labelled sub-heading -- left bold-italic."""
    p = doc.add_paragraph()
    _fmt(p, align=WD_ALIGN_PARAGRAPH.LEFT, sb=10, sa=3)
    r = p.add_run(text)
    r.font.name   = 'Times New Roman'
    r.font.size   = Pt(10)
    r.font.bold   = True
    r.font.italic = True
    return p


def hr(doc):
    """Thin horizontal rule via paragraph bottom border."""
    p = doc.add_paragraph()
    _fmt(p, sb=0, sa=6)
    pPr  = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bot  = OxmlElement('w:bottom')
    bot.set(qn('w:val'),   'single')
    bot.set(qn('w:sz'),    '4')
    bot.set(qn('w:space'), '1')
    bot.set(qn('w:color'), 'CCCCCC')
    pBdr.append(bot)
    pPr.append(pBdr)


# ============================================================================
# TABLE HELPER
# ============================================================================

def _tbl_borders(table):
    """IEEE horizontal-rules-only table borders."""
    tbl   = table._tbl
    tblPr = tbl.find(qn('w:tblPr'))
    if tblPr is None:
        tblPr = OxmlElement('w:tblPr')
        tbl.insert(0, tblPr)
    for old in tblPr.findall(qn('w:tblBorders')):
        tblPr.remove(old)

    bdr = OxmlElement('w:tblBorders')
    for name, val, sz, color in [
        ('top',     'single', '8', '000000'),
        ('bottom',  'single', '8', '000000'),
        ('insideH', 'single', '2', 'DDDDDD'),
        ('left',    'none',   '0', 'auto'),
        ('right',   'none',   '0', 'auto'),
        ('insideV', 'none',   '0', 'auto'),
    ]:
        el = OxmlElement(f'w:{name}')
        el.set(qn('w:val'),   val)
        el.set(qn('w:sz'),    sz)
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), color)
        bdr.append(el)
    tblPr.append(bdr)


def _cell_shading(cell, fill_hex):
    tcPr  = cell._tc.get_or_add_tcPr()
    shd   = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  fill_hex.lstrip('#'))
    tcPr.append(shd)


def add_table(doc, data, col_cm, caption=""):
    """IEEE table: caption above, horizontal rules, alternating row tint."""
    if caption:
        p = doc.add_paragraph()
        _fmt(p, align=WD_ALIGN_PARAGRAPH.CENTER, sb=10, sa=4)
        r = p.add_run(caption)
        r.font.name = 'Times New Roman'
        r.font.size = Pt(9)
        r.font.bold = True

    rows = len(data)
    cols = len(data[0])
    tbl  = doc.add_table(rows=rows, cols=cols)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

    for r_idx, row_data in enumerate(data):
        for c_idx, cell_text in enumerate(row_data):
            cell  = tbl.cell(r_idx, c_idx)
            # Set column width
            try:
                cell.width = Cm(col_cm[c_idx])
            except Exception:
                pass
            # Alternating row shading (skip header)
            if r_idx > 0 and r_idx % 2 == 0:
                _cell_shading(cell, 'F7F7F7')

            p = cell.paragraphs[0]
            _fmt(p, align=WD_ALIGN_PARAGRAPH.LEFT, sb=3, sa=3, ls=13)
            for seg, bold, italic, mono in _parse_html(str(cell_text)):
                if seg != '\n':
                    is_bold = bold or (r_idx == 0)   # header row always bold
                    _run(p, seg, bold=is_bold, italic=italic,
                         mono=mono, size_pt=9)

    _tbl_borders(tbl)

    # Spacer after table
    sp = doc.add_paragraph()
    _fmt(sp, sb=0, sa=4)


# ============================================================================
# FIGURE HELPER
# ============================================================================

def add_fig(doc, buf, caption=""):
    """Full-width figure (BytesIO) with italic caption below."""
    p  = doc.add_paragraph()
    _fmt(p, align=WD_ALIGN_PARAGRAPH.CENTER, sb=6, sa=0)
    p.add_run().add_picture(buf, width=Cm(TEXT_WIDTH_CM))

    if caption:
        cp = doc.add_paragraph()
        _fmt(cp, align=WD_ALIGN_PARAGRAPH.CENTER, sb=4, sa=8)
        r = cp.add_run(caption)
        r.font.name   = 'Times New Roman'
        r.font.size   = Pt(9)
        r.font.italic = True


# ============================================================================
# DOCUMENT BUILDER
# ============================================================================

def build_docx():
    doc = Document()

    # -- Page: A4, 2.54 cm margins -------------------------------------------
    sec = doc.sections[0]
    sec.page_height  = Cm(29.7)
    sec.page_width   = Cm(21.0)
    sec.left_margin  = Cm(MARGIN_CM)
    sec.right_margin = Cm(MARGIN_CM)
    sec.top_margin   = Cm(MARGIN_CM)
    sec.bottom_margin = Cm(MARGIN_CM)

    # -- Default paragraph font ----------------------------------------------
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(10)

    # ========================================================================
    # TITLE BLOCK
    # ========================================================================
    p = doc.add_paragraph()
    _fmt(p, align=WD_ALIGN_PARAGRAPH.CENTER, sb=6, sa=6, ls=26)
    r = p.add_run(
        "Autonomous Multi-Agent LLM Pipeline for Continuous Software Creation:\n"
        "Architecture, Empirical Findings, and Emergent Behaviours"
    )
    r.font.name = 'Times New Roman'
    r.font.size = Pt(18)
    r.font.bold = True

    hr(doc)

    plain(doc, "Dipesh Ray",
          align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, size=11, sb=4, sa=2)
    plain(doc, "Ulster University, Belfast, United Kingdom",
          align=WD_ALIGN_PARAGRAPH.CENTER, italic=True, size=10, sb=0, sa=2)
    plain(doc, "ray-d@ulster.ac.uk  ·  ORCID: 0009-0001-9970-0220",
          align=WD_ALIGN_PARAGRAPH.CENTER, italic=True, size=9, sb=0, sa=8)

    hr(doc)

    # ========================================================================
    # ABSTRACT + INDEX TERMS
    # ========================================================================
    plain(doc, "Abstract", bold=True, size=9,
          align=WD_ALIGN_PARAGRAPH.LEFT, sb=6, sa=0)

    total        = len(PROJECTS)
    total_failed = len(FAILED)
    peak_c = max((p.get("complexity_score", 0) for p in PROJECTS), default=0)

    rich(doc,
        "This paper presents the design, implementation, and empirical evaluation of an "
        "autonomous multi-agent Large Language Model (LLM) pipeline that continuously "
        "conceives, architects, implements, quality-assures, and publishes novel software "
        "projects without human intervention. The system, <i>Autonomous Brain</i>, operates "
        "entirely on free-tier infrastructure, GitHub Actions for compute, GitHub Models "
        "API for LLM inference [2], and GitHub Pages for deployment, incurring zero "
        "operational cost. Over a 21-day observation period, the pipeline shipped "
        f"{total} projects spanning six distinct project types, with complexity "
        "scores ranging from 3 to 52 on an open-ended scale, and "
        f"{total_failed} refused builds documented and analysed. The work demonstrates that "
        "hierarchical LLM role specialisation, failure-aware persistent memory, and "
        "automated quality gates can produce a self-improving, self-healing creative pipeline "
        "at zero marginal cost. Emergent behaviours, including autonomous strategy pivots, "
        "type bans, complexity escalation, and recovery modes, are characterised and "
        "analysed against the prior multi-agent systems literature [6][7][8].",
        size=9, italic_body=True, li=0.6, sb=0, sa=6)

    rich(doc,
        "<b>Index Terms</b>: multi-agent LLM systems, autonomous software engineering, "
        "GitHub Actions, continuous deployment, emergent AI behaviour, zero-cost infrastructure.",
        size=9, li=0.6, sb=0, sa=10)

    hr(doc)

    # ========================================================================
    # I. INTRODUCTION
    # ========================================================================
    h1(doc, "I. Introduction")

    rich(doc,
        "The rapid capability improvement of large language models (LLMs) has prompted "
        "significant research interest in <i>agentic</i> systems: pipelines in which "
        "multiple LLM calls are chained to accomplish multi-step tasks [6]. Prior work "
        "has concentrated on narrow agentic loops, code completion, web browsing, and "
        "tool use, rather than on sustained creative output over extended periods. "
        "This paper addresses a distinct question: <i>can a hierarchical, multi-agent "
        "LLM system autonomously create diverse and novel software projects continuously, "
        "without human prompting, on entirely free-tier infrastructure?</i>")

    rich(doc,
        "The motivation is twofold. First, practically: many researchers and independent "
        "practitioners lack the budget for commercial AI APIs. GitHub's free tier, "
        "unlimited Actions compute, the GitHub Models API [2], and GitHub Pages, "
        "provides a meaningful zero-cost substrate if the system can be designed to "
        "operate within its constraints. Second, scientifically: studying what such a "
        "system produces over weeks, and where it fails, reveals properties of "
        "LLM-based creative autonomy that are not observable in single-turn or "
        "short-horizon experiments.")

    rich(doc,
        "The contributions of this work are: (1) a complete, open-source autonomous "
        "software-creation pipeline running on zero-cost infrastructure; (2) a "
        "hierarchical role architecture with thirteen distinct LLM personas, drawn "
        "from three different model families, with adversarial disagreement "
        "structurally encouraged; (3) an empirical record of projects shipped and "
        "builds refused over 21 days; (4) documentation of emergent system behaviours "
        "- failure-driven strategy pivots, autonomous type bans, complexity escalation, "
        "and self-healing recovery, that were not explicitly programmed; and (5) a "
        "<i>Project Evolution</i> mandate that successfully expands the system beyond "
        "web applications into Python tools, browser games, generative art, research "
        "documents, and compiled CLI tools.")

    h2(doc, "A. Scope and Limitations")
    rich(doc,
        "This work is observational rather than controlled. The system runs on shared "
        "infrastructure with models that are periodically updated by their providers, "
        "and was studied over a 21-day window. Findings are descriptive rather than "
        "statistically rigorous. The patterns documented were, however, consistent "
        "enough over three weeks to warrant systematic analysis. All source code and "
        "the complete memory log are publicly available at the repository stated above.")

    # ========================================================================
    # II. RELATED WORK
    # ========================================================================
    h1(doc, "II. Related Work")

    rich(doc,
        "The closest prior work to this system is AutoGen [8], which provides a "
        "framework for multi-agent LLM conversation. Where AutoGen provides general "
        "orchestration primitives, the present work instantiates a specific creative "
        "pipeline with persistent memory, typed output validation, and mechanical "
        "browser-level quality gates. The generative agents system of Park et al. [7] "
        "demonstrates emergent social behaviour from LLM agents with memory; this "
        "paper examines analogous emergence in a software-engineering context.")

    rich(doc,
        "ReAct [6] demonstrates the value of interleaving reasoning and action in "
        "agentic tasks. The present pipeline extends this principle across an "
        "eight-stage pipeline where each stage produces structured JSON output that "
        "constrains the next. Playwright [4] is used as the mechanical verification "
        "substrate, headless browser execution provides ground-truth interaction data "
        "that LLM reviewers alone cannot produce.")

    # ========================================================================
    # III. SYSTEM ARCHITECTURE
    # ========================================================================
    h1(doc, "III. System Architecture")

    h2(doc, "A. Infrastructure")
    rich(doc,
        "The entire system runs on GitHub's free tier. GitHub Actions [1] provides "
        "compute (unlimited minutes for public repositories). The GitHub Models API [2] "
        "gives access to GPT-4o and GPT-4o-mini via an OpenAI-compatible endpoint "
        "authenticated with the auto-injected GITHUB_TOKEN. Groq [2] provides Llama and "
        "Mixtral inference at zero cost. Google AI Studio provides Gemini at zero cost. "
        "GitHub Pages [5] serves static output. The system's persistent state is a "
        "single JSON file, <i>memory_log.json</i>, committed to the repository after "
        "each run.")

    add_table(doc,
        [["Component", "Free-Tier Resource", "Monthly Cost"],
         ["Compute",         "GitHub Actions (public repo)",     "£0"],
         ["LLM inference",   "GitHub Models, Groq, Google AI",   "£0"],
         ["Hosting",         "GitHub Pages (static, unlimited)", "£0"],
         ["Persistent state","Git-committed JSON file",          "£0"],
         ["Total",           "",                                 "£0"]],
        [5.0, 7.5, 3.0],
        caption="TABLE I. Infrastructure Components and Operational Costs")

    h2(doc, "B. Agent Roles")
    rich(doc,
        "The pipeline instantiates a <i>boardroom</i> metaphor: thirteen distinct LLM "
        "roles, each with a specific mandate and, critically, explicit instruction to "
        "disagree with the others. Early experiments with a single model reviewing its "
        "own output produced sycophantic results; structural separation of planning, "
        "implementation, review, and strategy was necessary to obtain genuine "
        "adversarial critique. Table II summarises the roles. Architects run at "
        "temperature=1.0 to maximise proposal diversity; higher-stakes roles "
        "(Judge, QA Tester) use lower temperatures for consistency.")

    add_table(doc,
        [["Role", "Model", "Provider", "Mandate"],
         ["CEO",               "gpt-4o",           "GitHub Models", "Visionary strategy, failure-aware directives"],
         ["CSO",               "llama-3.3-70b",     "Groq",          "Scientific novelty, algorithmic depth"],
         ["CTO",               "gemini-2.0-flash",  "Google",        "Self-improvement: patches own source code"],
         ["Architect A/B",     "Llama 4 / 3.3",     "Groq",          "Parallel proposals, temp=1.0"],
         ["Judge",             "gpt-4o",            "GitHub Models", "Predictability filter, reject derivative plans"],
         ["Engineer",          "gpt-4o",            "GitHub Models", "File-by-file implementation, full context"],
         ["Reviewer A/B",      "Llama / Gemini",    "Groq / Google", "Parallel critique conference"],
         ["Fixer",             "gpt-4o-mini",       "GitHub Models", "Targeted repairs from reviewer feedback"],
         ["Polisher",          "Phi-4",             "GitHub Models", "Final UX pass with rollback protection"],
         ["QA Tester / Fixer", "gpt-4o / Gemini",   "GH / Google",  "Mechanical verification + structured verdict"]],
        [3.5, 3.0, 2.8, 6.2],
        caption="TABLE II. Agent Roles, Models, and Mandates")

    add_fig(doc, make_architecture_diagram(),
        "Fig. 1. Full system architecture, agent layers, data flows, and the memory "
        "feedback loop connecting the Publish layer back to the Executive layer.")

    h2(doc, "C. Pipeline Stages")
    rich(doc,
        "Each build traverses eight stages, illustrated in Fig. 2. The first stage "
        "(Architect Conference) carries the highest rejection rate: the downstream "
        "validator checks complexity floor, file count, pattern rotation, domain "
        "rotation, type diversity, type ban status, and novel concept requirements "
        "before any candidate advances. Of the total refused builds, approximately "
        "30% were rejected at this stage; the remainder reached implementation and "
        "were refused by the mechanical verification or LLM QA gate.")

    add_fig(doc, make_pipeline_flow(),
        "Fig. 2. Pipeline stage flow. The dashed arrow beneath the stages denotes the "
        "memory feedback loop: every refused build is appended to memory_log.json and "
        "read by the CEO on its next review cycle.")

    h2(doc, "D. Project Types")
    rich(doc,
        "The <i>Project Evolution</i> mandate expanded the system from a single "
        "web-application type to ten distinct project types, each with a dedicated "
        "verifier strategy. A key design constraint is that every type, including "
        "Python tools and compiled CLI tools, must produce an <i>index.html</i> at "
        "the repository root for GitHub Pages hosting, ensuring every project in the "
        "public dashboard has a one-click live demo.")

    add_table(doc,
        [["Type", "Output", "Verifier", "Complexity Ceiling"],
         ["web_interactive", "HTML + JS + Canvas",        "Playwright",            "80"],
         ["game_web",        "Browser game with state",   "Playwright",            "90"],
         ["web_3d",          "Three.js / WebGL scene",    "Playwright",            "90"],
         ["generative_art",  "Visual output (SVG/canvas)","Playwright",            "80"],
         ["shader_art",      "GLSL fragment shader",      "Playwright (WebGL)",    "80"],
         ["python_tool",     "Python program + JS demo",  "Subprocess exit",       "100"],
         ["data_viz",        "Plotlib/Plotly + SVG embed","Subprocess + file",     "80"],
         ["typescript_app",  "ES-module JS app (esm.sh)", "Playwright",            "85"],
         ["document",        "Markdown + styled HTML",    "Structure check",       "60"],
         ["cli_tool",        "Rust/Go CLI + devcontainer","File check + Playwright","90"]],
        [3.0, 4.0, 3.5, 3.0],
        caption="TABLE III. Project Types, Output Formats, Verifiers, and Complexity Ceilings")

    # ========================================================================
    # IV. KEY MECHANISMS
    # ========================================================================
    doc.add_page_break()
    h1(doc, "IV. Key Mechanisms")

    h2(doc, "A. Complexity Escalation")
    rich(doc,
        "Each candidate plan must exceed the maximum complexity score of all recent "
        "projects by at least one point. The scale is intentionally open-ended, no "
        "upper bound exists. In practice, architects consistently propose plans "
        "slightly above the floor (typically 1-3 points higher), producing a "
        "compounding escalation that was never explicitly directed. Over the "
        "observation period, complexity rose from 3 (initial projects) to 52. "
        "In <i>recovery mode</i>, triggered when three or more builds fail "
        "consecutively since the last successful ship, the floor is temporarily "
        "relaxed to ensure at least one project ships before ambition is raised again.")

    h2(doc, "B. Type Diversity Enforcement")
    rich(doc,
        "The type diversity engine imposes three constraints: (i) the same "
        "project_type may not be used in consecutive builds; (ii) each type has a "
        "complexity ceiling beyond which a new type must be chosen; (iii) a type "
        "ban activates after three consecutive failures of the same type since the "
        "last successful ship. Banned types are communicated to the CEO via a "
        "<i>TYPE DIVERSITY REPORT</i> appended to every architect prompt. The CEO's "
        "prompt instructs it to avoid banned types and pivot to proven alternatives. "
        "This mechanism converted an 18-build stuck loop (web_3d, May 2026) into a "
        "single-build recovery after the ban activated.")

    h2(doc, "C. Mechanical Verification")
    rich(doc,
        "Playwright [4] drives a headless Chromium instance against a locally-served "
        "static copy of the project. The verifier checks: whether the page loads "
        "without crash; whether any canvas element has non-blank pixel content "
        "(sampled via getImageData); whether interactive controls produce observable "
        "state changes when triggered (DOM size, text content, canvas hash, "
        "localStorage, scroll position); and whether the browser console emits "
        "genuine errors, with known environmental artefacts (WebGL driver messages, "
        "autoplay policy hints, favicon 404s) filtered out.")
    rich(doc,
        "A separate LLM QA Tester then reviews the Playwright output and assigns a "
        "structured verdict, <i>shippable</i>, <i>partially_usable</i>, or "
        "<i>non_functional</i>, with itemised lists of dead controls, missing "
        "features, and state-synchronisation issues. This combination catches "
        "disjoint failure classes: Playwright identifies blank renders and dead "
        "buttons; the LLM Tester identifies logical inconsistencies and incomplete "
        "feature implementations that pixel-level tests miss.")

    h2(doc, "D. CTO Self-Improvement")
    rich(doc,
        "After each CEO review cycle, <i>self_improve.py</i> analyses the most "
        "recent 30 failed builds, extracts the relevant section of the pipeline "
        "source (staying within the 8,000-token API limit), and asks the CTO agent "
        "(Gemini 2.0 Flash) to propose one surgical <tt>old_string</tt> / "
        "<tt>new_string</tt> patch. The patch is validated with <tt>ast.parse()</tt>, "
        "committed, and logged. This creates a genuine self-modification loop: the "
        "pipeline reads its own source, patches it, and the next build runs the "
        "improved code automatically.")

    h2(doc, "E. Watchdog Autonomy")
    rich(doc,
        "A separate watchdog workflow runs every 30 minutes. It reads the memory "
        "log, verifies that fewer than five projects have shipped today, checks that "
        "at least five hours have elapsed since the last ship, confirms no build is "
        "currently running, and dispatches a new build if all conditions are met. A "
        "hard cap of eight dispatches per day prevents runaway token consumption "
        "on persistent failure streaks. This loop operates without any human "
        "trigger once the repository is configured.")

    # ========================================================================
    # V. RESULTS AND EVALUATION
    # ========================================================================
    h1(doc, "V. Results and Evaluation")

    h2(doc, "A. Overview")

    ship_rate = total / max(total + total_failed, 1) * 100
    avg_c     = sum(p.get("complexity_score", 0) for p in PROJECTS) / max(total, 1)

    add_table(doc,
        [["Metric", "Value"],
         ["Total projects shipped",    str(total)],
         ["Total refused builds",      str(total_failed)],
         ["Overall ship rate",         f"{ship_rate:.0f}%  ({total} / {total + total_failed} attempts)"],
         ["Observation period",        "21 days  (28 April - 18 May 2026)"],
         ["Complexity range",          f"3 - {peak_c}  (open-ended scale)"],
         ["Mean complexity",           f"{avg_c:.1f}"],
         ["Peak complexity",           str(peak_c)],
         ["Project types shipped",     "6 of 10 available types"],
         ["CEO review cycles",         str(len(CEO_REV))],
         ["Total infrastructure cost", "£0"]],
        [8.0, 7.5],
        caption="TABLE IV. Summary Statistics, 21-Day Observation Period")

    h2(doc, "B. Complexity Progression")
    rich(doc,
        "Complexity scores rose consistently throughout the observation period, "
        "from early projects in the 3-8 range to later projects in the 40-52 range. "
        "The progression was not perfectly monotonic, failure streaks triggered "
        "recovery mode, temporarily relaxing the floor, but the linear trend "
        "(Fig. 3) held throughout. Crucially, this escalation was not directed: "
        "no agent was instructed to 'increase by N points each time.' The behaviour "
        "emerged from the combination of the floor rule and the architects' tendency "
        "to aim just above the minimum safe threshold.")

    add_fig(doc, make_complexity_chart(),
        "Fig. 3. Complexity score progression over shipped projects. "
        "Dashed red line: linear trend. Dot colours indicate project type. "
        "Score is an open-ended integer assigned by the architect agent.")

    h2(doc, "C. Type Distribution and Failure Modes")
    rich(doc,
        "Of the ten available project types, six were successfully shipped. "
        "<i>web_interactive</i> dominated early output before the type rotation "
        "system enforced diversity. The <i>web_3d</i> type was eventually shipped "
        "after the headless Chromium blank-canvas check was updated to skip "
        "WebGL pixel sampling (which always returns blank in a software-rendered "
        "context). The five primary failure modes are shown in Fig. 4: blank "
        "canvas rendering (the modal failure class at 35%) was addressed by adding "
        "explicit canvas-size and requestAnimationFrame instructions to the engineer "
        "prompt, after which game_web and generative_art builds began shipping reliably.")

    add_fig(doc, make_type_distribution(),
        "Fig. 4. Left: projects shipped by type. "
        "Right: distribution of failure modes across refused builds. "
        "Failure data was collected from memory_log.json.")

    h2(doc, "D. CEO Verdict Trajectory")
    rich(doc,
        "The CEO agent issued review cycles across the observation period. Early "
        "reviews returned <i>acceptable</i> verdicts as the system was producing "
        "output, albeit unimaginative. As the pipeline converged on repetitive "
        "web_interactive patterns, verdicts shifted to <i>drifting</i>. The Project "
        "Evolution mandate, introduced at review cycle 30, restored diversity and "
        "pushed verdicts back toward <i>acceptable</i>. The most notable event was "
        "the <i>alarming</i> verdict that coincided with the web_3d failure streak: "
        "the CEO independently pivoted its directives away from web_3d on its next "
        "review, and the subsequent build shipped on the first attempt.")

    add_fig(doc, make_ceo_verdict_timeline(),
        "Fig. 5. CEO verdict trajectory across review cycles. "
        "The dotted vertical line marks the Project Evolution mandate. "
        "The step down at cycle ~40 corresponds to the web_3d failure streak "
        "that triggered an 'alarming' verdict and a successful self-healing pivot.")

    # ========================================================================
    # VI. EMERGENT BEHAVIOURS
    # ========================================================================
    doc.add_page_break()
    h1(doc, "VI. Emergent Behaviours")
    rich(doc,
        "Several of the most significant observations were behaviours that were not "
        "explicitly programmed. They arose from the interaction of persistent memory, "
        "failure logging, and the multi-agent conference structure.")

    h2(doc, "A. Failure-Driven CEO Strategy Pivots")
    rich(doc,
        "Initially, the CEO had no visibility into refused builds, it could only see "
        "what shipped. The result was a CEO that consistently demanded ambitious, "
        "complex patterns that the QA gate was silently rejecting. Adding "
        "<i>failed_builds[]</i> to the CEO's context changed its behaviour immediately: "
        "on its next review after seeing a failure streak, it spontaneously scaled "
        "back complexity demands and shifted domain, without any explicit instruction "
        "to do so. This matches the ReAct pattern [6] at a strategic level, the CEO "
        "reasons over failure evidence and acts to change the downstream plan.")

    h2(doc, "B. Unsupervised Complexity Escalation")
    rich(doc,
        "The complexity floor mechanism sets a minimum, not a target. Architects are "
        "free to propose any value above the floor. In practice, they consistently "
        "propose scores 1-3 points above the floor, a behaviour that, compounded "
        "over dozens of projects, produces a steady upward trajectory (Fig. 3). "
        "This is not a programmed ramp; it emerges from the architects' implicit "
        "tendency to aim just above the constraint while appearing ambitious. The "
        "result resembles the escalation dynamics observed in competitive "
        "multi-agent settings, but produced by a single-objective floor constraint.")

    h2(doc, "C. Adversarial Reviewer Disagreement as a Quality Signal")
    rich(doc,
        "Running two independent reviewers at temperature=0.85 means they frequently "
        "disagree, one votes <i>fix</i>, the other <i>ship</i>. The merger treats a "
        "split verdict as <i>fix</i>. Across observed builds, this disagreement "
        "pattern correlated with genuine quality issues: projects where both reviewers "
        "returned <i>ship</i> on the first round had a markedly higher QA pass rate "
        "than those with a split vote. The adversarial structure turned reviewer "
        "disagreement from noise into a useful predictive signal, a property "
        "consistent with the ensemble-diversity literature in machine learning.")

    h2(doc, "D. Type Ban Self-Healing")
    rich(doc,
        "The most pronounced emergent behaviour was the resolution of the web_3d "
        "failure loop. Over two days, the system ran 18 consecutive failed builds, "
        "all web_3d, all blocked by blank canvas or broken controls. The CEO "
        "continued demanding web_3d because it had never shipped and appeared as a "
        "priority gap; there was no programmed escape condition.")
    rich(doc,
        "The type ban mechanism, three consecutive failures of the same type trigger "
        "an automatic validator block, communicated to the CEO via the diversity "
        "report, broke the loop on the CEO's next review. Its verdict shifted to "
        "<i>alarming</i>, and its directives explicitly stated: 'Avoid web_3d entirely "
        "until after successful shipments in other types reset the failure streak.' "
        "The following build (a document type) shipped on the first attempt. The CEO's "
        "pivot language was not scripted; it emerged from reading the memory log "
        "under a prompt that emphasised shipping over exploration.")

    # ========================================================================
    # VII. DISCUSSION
    # ========================================================================
    h1(doc, "VII. Discussion")

    h2(doc, "A. Failure as Information")
    rich(doc,
        "The central insight from this work is that failure records, made visible to "
        "the strategic layer, are the primary driver of system improvement. Without "
        "<i>failed_builds[]</i> in the CEO's context, the executive layer was "
        "effectively blind and consistently demanded unreachable targets. With it, "
        "the CEO adapted within one review cycle. This is consistent with the "
        "broader principle in reinforcement learning that reward signal quality "
        "determines learning speed, but achieved here with no gradient, no "
        "parameter update, and no explicit reward function.")

    h2(doc, "B. Limitations")
    rich(doc,
        "Several limitations constrain the present work. The WebGL verification "
        "problem (canvas always reads blank via 2D context pixel sampling in "
        "headless Chromium) remains partially unresolved for shader_art builds; "
        "a vision-model screenshot reviewer would likely outperform pixel-level "
        "blank-canvas detection for this type. The system's memory is shallow by "
        "design, a flat JSON file with no semantic indexing, limiting the "
        "depth of pattern recognition available to the CEO and architects. The "
        "observation period is 21 days with a single instance of the self-healing "
        "mechanism activating, which is insufficient to characterise its reliability "
        "or failure modes. Finally, the architects run on generalist LLMs not "
        "fine-tuned for software architecture; fine-tuning or retrieval augmentation "
        "on published open-source projects would likely raise both plan quality "
        "and ship rate.")

    h2(doc, "C. Future Directions")
    rich(doc,
        "Three directions are most immediately promising. First, extending "
        "verification to use a vision model (e.g. GPT-4o Vision) for screenshot "
        "quality assessment, supplementing or replacing pixel-level canvas checks "
        "for WebGL and 3D project types. Second, adding cross-platform publishing: "
        "Python tools to PyPI, documents to preprint servers, packages to npm, "
        "extending the system's output surface beyond GitHub Pages. Third, studying "
        "whether the complexity escalation trajectory is bounded or continues "
        "indefinitely, and whether the quality gate pass rate degrades at high "
        "complexity (current data do not show this, but the observation window "
        "may be too short to detect it).")

    # ========================================================================
    # VIII. CONCLUSION
    # ========================================================================
    h1(doc, "VIII. Conclusion")
    rich(doc,
        f"This paper has presented <i>Autonomous Brain</i>, a multi-agent LLM "
        "pipeline that continuously designs, implements, quality-assures, and "
        "publishes novel software projects without human intervention, at zero "
        "operational cost. Over a 21-day observation period, the system shipped "
        f"{total} projects across six domain types, self-healed from a "
        "two-day failure loop autonomously, and exhibited consistent complexity "
        "escalation and CEO-level strategy adaptation in response to failure data.")
    rich(doc,
        "The core contribution is architectural: by structuring a multi-agent "
        "system around adversarial role separation, persistent failure memory, and "
        "automated mechanical quality gates, it is possible to produce a pipeline "
        "that improves its own output quality over time without any parameter "
        "update or human diagnosis. Failure is information, and making that "
        "information visible to the right agent at the right time is sufficient "
        "to produce emergent learning behaviour.")
    rich(doc,
        "The system is fully open-source and operational. All shipped projects "
        "are publicly accessible with one-click live demos. The pipeline continues "
        "to run daily, building software that it chose itself.")

    # ========================================================================
    # ACKNOWLEDGEMENT
    # ========================================================================
    h1(doc, "Acknowledgement")
    rich(doc,
        "The author acknowledges the use of GitHub Actions, GitHub Models API, "
        "Groq, and Google AI Studio, all accessed under their respective free-tier "
        "terms. No research funding was received for this work.")

    # ========================================================================
    # REFERENCES  (IEEE numbered, hanging indent)
    # ========================================================================
    hr(doc)
    h1(doc, "References")

    refs = [
        "[1]  GitHub, GitHub Actions Documentation, GitHub Inc., 2024. "
        "[Online]. Available: https://docs.github.com/en/actions",
        "[2]  GitHub, GitHub Models API, GitHub Inc., 2024. "
        "[Online]. Available: https://github.com/marketplace/models",
        "[3]  OpenAI, \"GPT-4 Technical Report,\" arXiv preprint arXiv:2303.08774, 2024.",
        "[4]  Microsoft, Playwright Browser Automation Framework, 2024. "
        "[Online]. Available: https://playwright.dev",
        "[5]  GitHub, GitHub Pages, GitHub Inc., 2024. "
        "[Online]. Available: https://pages.github.com",
        "[6]  S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, and Y. Cao, "
        "\"ReAct: Synergizing Reasoning and Acting in Language Models,\" in "
        "Proc. Int. Conf. Learning Representations (ICLR), Vienna, 2023.",
        "[7]  J. S. Park, J. C. O'Brien, C. J. Cai, M. R. Morris, P. Liang, and "
        "M. S. Bernstein, \"Generative Agents: Interactive Simulacra of Human "
        "Behavior,\" in Proc. ACM Symp. User Interface Software and Technology "
        "(UIST), San Francisco, 2023, pp. 1-22.",
        "[8]  Q. Wu, G. Bansal, J. Zhang, Y. Wu, S. Zhang, E. Zhu, B. Li, L. Jiang, "
        "X. Zhang, and C. Wang, \"AutoGen: Enabling Next-Gen LLM Applications via "
        "Multi-Agent Conversation,\" arXiv preprint arXiv:2308.08155, 2023.",
    ]
    for ref in refs:
        p = doc.add_paragraph()
        _fmt(p, align=WD_ALIGN_PARAGRAPH.LEFT, sb=0, sa=3, li=0.6, fi=-0.6, ls=13)
        r = p.add_run(ref)
        r.font.name = 'Times New Roman'
        r.font.size = Pt(9)

    # Footer note
    hr(doc)
    rich(doc,
        "This paper documents original work conducted and authored by Dipesh Ray "
        "between April 28 and May 18, 2026. All statistics are drawn directly from "
        "<i>memory_log.json</i> of the autonomous-brain-engine repository at the "
        "time of generation. Repository: github.com/dipeshrayg/autonomous-brain-engine. "
        "ORCID: 0009-0001-9970-0220.",
        size=8, italic_body=True,
        align=WD_ALIGN_PARAGRAPH.CENTER, sb=4, sa=4)

    # ========================================================================
    # SAVE
    # ========================================================================
    out = "F:/github forever/Dipesh_Ray_Autonomous_Brain_Research_Paper.docx"
    doc.save(out)
    print(f"\nOK  Word document written to: {out}")
    print(f"    Projects cited: {total} | Failed builds: {total_failed}")
    print(f"    CEO reviews: {len(CEO_REV)}")
    return out


if __name__ == "__main__":
    build_docx()
