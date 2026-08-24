/**
 * AI Resume Analyzer — Frontend Script
 * Handles: upload, analysis, improved resume generation, modal, PDF download.
 */

// ══════════════════════════════════════════════════════════
// SCROLL ANIMATION ENGINE
// ══════════════════════════════════════════════════════════

// ── Smooth scroll for all internal anchor links ───────────
document.addEventListener('click', e => {
  const link = e.target.closest('a[href^="#"]');
  if (!link) return;
  const target = document.querySelector(link.getAttribute('href'));
  if (target) {
    e.preventDefault();
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
});

// ── IntersectionObserver reveal engine ───────────────────
const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('is-visible');
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

// Observe all pre-marked static reveal elements
document.querySelectorAll('.reveal-item, .reveal-left, .reveal-right, .reveal-scale')
  .forEach(el => revealObserver.observe(el));

/**
 * Animate a freshly-rendered container: adds reveal + stagger classes
 * to all direct children matching `selector`, then observes them.
 * @param {string} containerId  — ID of the parent container
 * @param {string} selector     — child selector (default: all children)
 * @param {string} animClass    — one of: reveal-item | reveal-left | reveal-right | reveal-scale
 */
function animateChildren(containerId, selector = '*', animClass = 'reveal-item') {
  const container = document.getElementById(containerId);
  if (!container) return;
  const children = container.querySelectorAll(selector);
  children.forEach((el, i) => {
    el.classList.add(animClass, `stagger-${Math.min(i + 1, 7)}`);
    revealObserver.observe(el);
  });
}

/**
 * Animate a single element with optional delay.
 */
function animateEl(el, animClass = 'reveal-item', delayMs = 0) {
  if (!el) return;
  el.style.transitionDelay = delayMs + 'ms';
  el.classList.add(animClass);
  revealObserver.observe(el);
}

/**
 * Animate chips with staggered chipPop keyframe.
 */
function animateChips(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.querySelectorAll('span').forEach((chip, i) => {
    chip.style.animationDelay = (i * 55) + 'ms';
    chip.classList.add('chip-animate');
  });
}

// ── Element References ────────────────────────────────────────────
const dropZone            = document.getElementById('drop-zone');
const resumeInput         = document.getElementById('resume-input');
const browseBtn           = document.getElementById('browse-btn');
const fileSelectedEl      = document.getElementById('file-selected');
const fileNameEl          = document.getElementById('file-name');
const fileSizeEl          = document.getElementById('file-size');
const fileRemoveBtn       = document.getElementById('file-remove');
const analyzeBtn          = document.getElementById('analyze-btn');
const uploadForm          = document.getElementById('upload-form');
const notification        = document.getElementById('notification');
const loadingOverlay      = document.getElementById('loading-overlay');
const improveLoadingOverlay = document.getElementById('improve-loading-overlay');
const resultsSection      = document.getElementById('results-section');
const reanalyzeBtn        = document.getElementById('reanalyze-btn');
const improveBtn          = document.getElementById('improve-btn');
const improveModal        = document.getElementById('improve-modal');
const modalClose          = document.getElementById('modal-close');
const resumePreview       = document.getElementById('resume-preview');
const copyBtn             = document.getElementById('copy-btn');
const downloadBtn         = document.getElementById('download-btn');

let selectedFile  = null;   // Currently selected File object
let lastResumeText = '';    // Stored after analysis for /improve call
let lastAnalysisScore = 0; // Stored original score for /compare call
let lastImprovedText = ''; // Flattened improved resume text for /compare
let lastBreakdown = {};    // Score breakdown from last analysis
let lastAtsOptimizations = []; // ATS optimization list from last improve call
let lastOptReport = null;  // Optimization report from last improve call
let lastCareerStage = 'student'; // Detected career stage
let lastPotentialData = null;    // Potential score + improvement roadmap


// ── Helpers ───────────────────────────────────────────────────────
function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}
function showNotification(msg, type = 'error') {
  notification.textContent = msg;
  notification.className = `notification ${type}`;
}
function hideNotification() { notification.className = 'notification hidden'; }

// ── File Handling ─────────────────────────────────────────────────
function handleFile(file) {
  hideNotification();
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    showNotification('❌ Invalid file. Please upload a PDF file only.', 'error'); return;
  }
  if (file.size > 10 * 1024 * 1024) {
    showNotification('❌ File too large. Maximum allowed size is 10 MB.', 'error'); return;
  }
  selectedFile = file;
  fileNameEl.textContent = file.name;
  fileSizeEl.textContent = formatSize(file.size);
  dropZone.querySelector('.drop-zone-inner').style.display = 'none';
  fileSelectedEl.style.display = 'flex';
  analyzeBtn.disabled = false;
}
function clearFile() {
  selectedFile = null;
  resumeInput.value = '';
  dropZone.querySelector('.drop-zone-inner').style.display = '';
  fileSelectedEl.style.display = 'none';
  analyzeBtn.disabled = true;
  hideNotification();
}

// ── Drag & Drop ───────────────────────────────────────────────────
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault(); dropZone.classList.remove('dragover');
  const file = e.dataTransfer.files[0]; if (file) handleFile(file);
});
dropZone.addEventListener('click', e => {
  if (!fileSelectedEl.contains(e.target)) resumeInput.click();
});
browseBtn.addEventListener('click', e => { e.stopPropagation(); resumeInput.click(); });
resumeInput.addEventListener('change', () => { if (resumeInput.files[0]) handleFile(resumeInput.files[0]); });
fileRemoveBtn.addEventListener('click', e => { e.stopPropagation(); clearFile(); });

// ── Loading Step Helpers ──────────────────────────────────────────
let stepTimers     = [];
let progressAnimId = null;

function startProgressBar(overlayEl) {
  const fill = overlayEl.querySelector('.loading-progress-fill');
  const pct  = overlayEl.querySelector('.loading-progress-pct');
  if (!fill) return;

  // Hard-reset without transition so it snaps to 0
  fill.style.transition = 'none';
  fill.style.width = '0%';
  if (pct) pct.textContent = '0%';

  // Ease-out quad to 88% over 25 s — never reaches 100% on its own
  const DURATION = 25000;
  const MAX_PCT  = 88;
  const startTime = performance.now();

  function tick(now) {
    const t     = Math.min((now - startTime) / DURATION, 1);
    const eased = 1 - Math.pow(1 - t, 2);          // ease-out quadratic
    const value = Math.round(eased * MAX_PCT);
    fill.style.transition = 'width 0.5s ease';
    fill.style.width = value + '%';
    if (pct) pct.textContent = value + '%';
    if (t < 1) progressAnimId = requestAnimationFrame(tick);
  }
  progressAnimId = requestAnimationFrame(tick);
}

function stopProgressBar(overlayEl) {
  if (progressAnimId) { cancelAnimationFrame(progressAnimId); progressAnimId = null; }
  const fill = overlayEl.querySelector('.loading-progress-fill');
  const pct  = overlayEl.querySelector('.loading-progress-pct');
  if (fill) { fill.style.transition = 'width 0.3s ease'; fill.style.width = '100%'; }
  if (pct)  pct.textContent = '100%';
}

function startLoadingSteps(prefix, messages, overlayEl) {
  messages.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active', 'done');
  });
  if (messages[0]) document.getElementById(messages[0])?.classList.add('active');

  messages.slice(1).forEach((id, i) => {
    stepTimers.push(setTimeout(() => {
      document.getElementById(messages[i])?.classList.replace('active', 'done');
      document.getElementById(id)?.classList.add('active');
    }, (i + 1) * 5000));
  });

  startProgressBar(overlayEl);
  overlayEl.classList.add('active');
}
function stopLoadingSteps(overlayEl) {
  stepTimers.forEach(clearTimeout); stepTimers = [];
  stopProgressBar(overlayEl);
  setTimeout(() => overlayEl.classList.remove('active'), 350);
}

// ── Sub-Score Circular Gauge Helper ──────────────────────────────
function buildGauge(value, color) {
  const r = 28, circ = 2 * Math.PI * r;
  const offset = circ - (value / 100) * circ;
  return `<svg width="72" height="72" viewBox="0 0 72 72">
    <circle cx="36" cy="36" r="${r}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="6"/>
    <circle cx="36" cy="36" r="${r}" fill="none" stroke="${color}" stroke-width="6"
      stroke-linecap="round" stroke-dasharray="${circ.toFixed(2)}"
      stroke-dashoffset="${circ.toFixed(2)}"
      data-offset="${offset.toFixed(2)}"
      style="transform:rotate(-90deg);transform-origin:50% 50%;transition:stroke-dashoffset 1.4s cubic-bezier(.4,0,.2,1)"/>
    <text x="36" y="41" text-anchor="middle" fill="${color}" font-size="14" font-weight="800" font-family="Inter,sans-serif">${value}</text>
  </svg>`;
}

// ── Render Sub-Scores Row ─────────────────────────────────────────
function renderSubScores(sub) {
  const grid = document.getElementById('sub-scores-grid');
  if (!grid || !sub) return;

  const strengthColors = {
    'Weak':      { bg: 'rgba(244,63,94,0.1)',  border: 'rgba(244,63,94,0.35)',  text: '#fb7185' },
    'Average':   { bg: 'rgba(251,191,36,0.1)', border: 'rgba(251,191,36,0.35)', text: '#fcd34d' },
    'Good':      { bg: 'rgba(14,165,233,0.1)', border: 'rgba(14,165,233,0.35)', text: '#38bdf8' },
    'Excellent': { bg: 'rgba(16,185,129,0.1)', border: 'rgba(16,185,129,0.35)', text: '#34d399' },
  };

  const metrics = [
    { key: 'ats_score',           label: 'ATS Compliance',     color: '#38bdf8' },
    { key: 'technical_score',     label: 'Technical Depth',    color: '#a78bfa' },
    { key: 'project_score',       label: 'Project Quality',     color: '#fb923c' },
    { key: 'communication_score', label: 'Communication',      color: '#34d399' },
  ];

  let cardsHtml = metrics.map(m => {
    const val = sub[m.key] ?? 0;
    return `<div class="sub-score-card">
      <div class="sub-score-gauge">${buildGauge(val, m.color)}</div>
      <div class="sub-score-label">${m.label}</div>
    </div>`;
  }).join('');

  // Overall Strength badge card
  const strength = sub.overall_strength || 'Average';
  const sc = strengthColors[strength] || strengthColors['Average'];
  cardsHtml += `<div class="sub-score-card sub-score-strength"
    style="background:${sc.bg};border-color:${sc.border};">
    <div class="strength-icon">🏆</div>
    <div class="strength-label">Overall Strength</div>
    <div class="strength-value" style="color:${sc.text}">${strength}</div>
  </div>`;

  grid.innerHTML = cardsHtml;

  // Animate gauges after render
  requestAnimationFrame(() => {
    grid.querySelectorAll('circle[data-offset]').forEach(c => {
      c.style.strokeDashoffset = c.dataset.offset;
    });
  });
}

// ── Render Score Explanation ──────────────────────────────────────
function renderScoreExplanation(exp) {
  const card = document.getElementById('score-explanation-card');
  if (!card || !exp) return;

  const why = exp.why_this_score || '';
  const reduced = exp.areas_that_reduced_score || [];
  const well    = exp.areas_that_performed_well || [];

  if (!why && !reduced.length && !well.length) return;

  document.getElementById('explanation-why-text').textContent = why;
  document.getElementById('explanation-reduced-list').innerHTML =
    reduced.map(r => `<li><span class="expl-dot expl-dot-red">▼</span>${esc(r)}</li>`).join('');
  document.getElementById('explanation-well-list').innerHTML =
    well.map(w => `<li><span class="expl-dot expl-dot-green">▲</span>${esc(w)}</li>`).join('');

  card.style.display = 'block';
}

// ── Render Analysis Results ───────────────────────────────────────
function renderResults(analysis) {
  animateScore(analysis.score);
  const { label, color } = getScoreLabel(analysis.score);
  const levelEl = document.getElementById('score-level');
  levelEl.textContent = label; levelEl.style.color = color;

  // 7-category score breakdown bars
  const breakdownEl = document.getElementById('score-breakdown');
  const bd = analysis.score_breakdown || {};
  
  let items = [];
  if (analysis.stage_rubric) {
    items = Object.entries(analysis.stage_rubric).map(([key, data]) => ({
      label: data.label,
      key: key,
      max: data.max
    }));
  } else {
    // Fallback for older analysis results
    items = [
      { label: 'Skills Relevance',       key: 'skills_relevance',       max: 20 },
      { label: 'Project Quality',        key: 'project_quality',        max: 20 },
      { label: 'ATS Optimization',       key: 'ats_optimization',       max: 15 },
      { label: 'Experience Impact',      key: 'experience_impact',      max: 15 },
      { label: 'Formatting & Structure', key: 'formatting_structure',   max: 10 },
      { label: 'Grammar & Clarity',      key: 'grammar_clarity',        max: 10 },
      { label: 'Education & Certs',      key: 'education_certifications', max: 10 },
    ];
  }

  breakdownEl.innerHTML = items.map(item => {
    const val = bd[item.key] ?? 0;
    const pct = Math.round((val / item.max) * 100);
    const barColor = pct >= 75 ? '#10b981' : pct >= 50 ? '#0ea5e9' : '#f59e0b';
    return `<div class="breakdown-item">
      <span class="breakdown-label">${item.label}</span>
      <div class="breakdown-bar-wrap"><div class="breakdown-bar" style="width:0%;background:${barColor}" data-width="${pct}%"></div></div>
      <span class="breakdown-val">${val}/${item.max}</span>
    </div>`;
  }).join('');
  setTimeout(() => {
    breakdownEl.querySelectorAll('.breakdown-bar').forEach(b => b.style.width = b.dataset.width);
  }, 300);

  document.getElementById('ai-summary').textContent = analysis.summary || '—';
  document.getElementById('experience-badge').textContent = analysis.experience_level || '';
  document.getElementById('job-titles').innerHTML = (analysis.job_titles_suggested || [])
    .map(t => `<span class="job-tag">${t}</span>`).join('');

  document.getElementById('skills-container').innerHTML = (analysis.skills_detected || [])
    .map(s => `<span class="skill-tag">${s}</span>`).join('');

  const ats = analysis.ats_feedback || {};
  const friendly = ats.is_ats_friendly;
  document.getElementById('ats-content').innerHTML = `
    <div class="ats-score-row">
      <div class="ats-score-circle ${friendly ? 'ats-friendly' : 'ats-unfriendly'}">${ats.ats_score ?? 0}</div>
      <div><strong style="font-size:15px;font-weight:700;">${friendly ? 'ATS Compliant Document' : 'Non-Compliant Format'}</strong><br/>
      <span style="font-size:12.5px;color:var(--text-muted)">ATS Structural Compliance Rating</span></div>
    </div>
    ${ats.issues?.length ? `<p class="ats-issues-label">Issues Found</p><ul class="ats-list">${ats.issues.map(i=>`<li>${i}</li>`).join('')}</ul>` : ''}
    ${ats.tips?.length   ? `<p class="ats-tips-label">Optimization Tips</p><ul class="ats-list">${ats.tips.map(t=>`<li>${t}</li>`).join('')}</ul>` : ''}`;

  document.getElementById('strengths-list').innerHTML  = (analysis.strengths  || []).map(s=>`<li>${s}</li>`).join('');
  document.getElementById('weaknesses-list').innerHTML = (analysis.weaknesses || []).map(w=>`<li>${w}</li>`).join('');
  document.getElementById('missing-skills-container').innerHTML = (analysis.missing_skills || [])
    .map(s=>`<span class="missing-tag">+ ${s}</span>`).join('');
  document.getElementById('suggestions-list').innerHTML = (analysis.suggestions || []).map(s=>`<li>${s}</li>`).join('');

  // Sub-scores and explanation (new)
  renderSubScores(analysis.sub_scores);
  renderScoreExplanation(analysis.score_explanation);

  resultsSection.classList.remove('hidden');
  setTimeout(() => resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' }), 200);

  // ── Trigger scroll animations for all dynamic content ──
  setTimeout(() => {
    // Score banner + circle
    animateEl(document.getElementById('score-banner'), 'reveal-item', 0);

    // Score breakdown bars
    animateEl(document.getElementById('score-breakdown'), 'reveal-left', 80);

    // Sub-score cards (staggered)
    animateChildren('sub-scores-grid', '.sub-score-card', 'reveal-item');

    // Score explanation card
    animateEl(document.getElementById('score-explanation-card'), 'reveal-item', 100);

    // Skills chips (pop animation)
    animateChips('skills-container');

    // Strengths / weaknesses lists (staggered)
    animateChildren('strengths-list', 'li', 'reveal-item');
    animateChildren('weaknesses-list', 'li', 'reveal-item');

    // Missing skills chips
    animateChips('missing-skills-container');

    // Suggestions list
    animateChildren('suggestions-list', 'li', 'reveal-item');

    // ATS card
    animateEl(document.getElementById('ats-content'), 'reveal-scale', 120);

    // Career stage badge
    animateEl(document.getElementById('career-stage-badge'), 'reveal-item', 60);
  }, 250);
}

// ── Score Ring Animation ──────────────────────────────────────────
function animateScore(score) {
  const circumference = 427.26;
  const fill = document.getElementById('score-ring-fill');
  const svgEl = fill.closest('svg');
  if (!svgEl.querySelector('defs')) {
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `<linearGradient id="scoreGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#6c63ff"/>
      <stop offset="100%" stop-color="#a78bfa"/>
    </linearGradient>`;
    svgEl.prepend(defs);
  }
  requestAnimationFrame(() => {
    fill.style.strokeDashoffset = circumference - (score / 100) * circumference;
  });
  const numberEl = document.getElementById('score-number');
  const startTime = performance.now();
  function tick(now) {
    const progress = Math.min((now - startTime) / 1500, 1);
    numberEl.textContent = Math.round(progress * score);
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function getScoreLabel(score) {
  if (score >= 85) return { label: 'Excellent Resume Quality', color: '#10b981' };
  if (score >= 70) return { label: 'Good Overall Resume',     color: '#6366f1' };
  if (score >= 50) return { label: 'Needs Strategic Rework', color: '#f59e0b' };
  return              { label: 'Significant Rework Needed', color: '#ef4444' };
}


// ── Stage Badge ───────────────────────────────────────────────────
function renderStageBadge(stage, label) {
  let el = document.getElementById('career-stage-badge');
  if (!el) return;
  const colors = {
    student: '#6c63ff', early: '#0ea5e9', mid: '#10b981', senior: '#f59e0b'
  };
  const color = colors[stage] || '#6c63ff';
  el.innerHTML = `<span style="
    display:inline-flex; align-items:center; gap:6px; padding:4px 12px;
    background:${color}18; border:1px solid ${color}44; border-radius:99px;
    font-size:11.5px; font-weight:600; color:${color}; letter-spacing:0.2px;">
    📋 Evaluated as: ${esc(label || 'Student / Fresher')}
  </span>`;
  el.style.display = 'block';
}



uploadForm.addEventListener('submit', async e => {
  e.preventDefault(); hideNotification();
  if (!selectedFile) { showNotification('❌ Please select a PDF resume.', 'error'); return; }

  startLoadingSteps('step', ['step-1','step-2','step-3'], loadingOverlay);
  analyzeBtn.disabled = true;

  const formData = new FormData();
  formData.append('resume', selectedFile);

  try {
    const resp = await fetch('/analyze', { method: 'POST', body: formData });
    let data = {};
    const contentType = resp.headers.get('content-type') || '';

    if (contentType.includes('application/json')) {
      data = await resp.json();
    } else {
      const rawText = await resp.text();
      throw new Error(`Server returned HTTP ${resp.status}: ${rawText.substring(0, 150)}`);
    }

    stopLoadingSteps(loadingOverlay);

    if (!resp.ok || data.error) {
      showNotification(`❌ ${data.error || 'Analysis failed.'}`, 'error');
      analyzeBtn.disabled = false; return;
    }
    // Store resume_text for the improve step
    lastResumeText    = data.resume_text || '';
    lastAnalysisScore = data.analysis?.score || 0;
    lastBreakdown     = data.analysis?.score_breakdown || {};
    lastCareerStage   = data.career_stage  || 'student';
    lastPotentialData = data.potential_data || null;
    showNotification('✅ Analysis complete! Scroll down to view your results.', 'success');
    renderResults(data.analysis);
    renderStageBadge(data.career_stage, data.stage_label);

  } catch (err) {
    stopLoadingSteps(loadingOverlay);
    showNotification(`❌ ${err.message}`, 'error');
    analyzeBtn.disabled = false;
  }
});

// ── Re-analyze Button ─────────────────────────────────────────────
reanalyzeBtn.addEventListener('click', () => {
  resultsSection.classList.add('hidden');
  clearFile(); hideNotification();
  lastResumeText = '';
  lastAnalysisScore = 0;
  lastImprovedText = '';
  lastBreakdown = {};
  lastAtsOptimizations = [];
  lastOptReport = null;
  lastCareerStage = 'student';
  lastPotentialData = null;

  document.getElementById('upload-section').scrollIntoView({ behavior: 'smooth' });
});

// ── Flatten improved_data to plain text for /compare ─────────────
function flattenImprovedData(d) {
  const lines = [];
  if (d.candidate_name) lines.push(d.candidate_name);
  const c = d.contact || {};
  [c.email, c.phone, c.location, c.linkedin, c.github].filter(Boolean).forEach(v => lines.push(v));
  if (d.professional_summary) lines.push(d.professional_summary);
  for (const job of (d.experience || [])) {
    lines.push(`${job.title} at ${job.company} (${job.duration})`);
    (job.bullets || []).forEach(b => lines.push('• ' + b));
  }
  for (const edu of (d.education || [])) {
    lines.push(`${edu.degree} at ${edu.institution} (${edu.duration})`);
    if (edu.details) lines.push(edu.details);
  }
  const sk = d.skills || {};
  ['languages','frameworks','tools','other'].forEach(k => {
    if (sk[k]?.length) lines.push(k + ': ' + sk[k].join(', '));
  });
  for (const proj of (d.projects || [])) {
    lines.push(`${proj.name} (${proj.tech})`);
    (proj.bullets || []).forEach(b => lines.push('• ' + b));
  }
  (d.certifications || []).forEach(c => lines.push(c));
  (d.achievements || []).forEach(a => lines.push(a));
  return lines.join('\n');
}

// ── Render Comparison Panel ───────────────────────────────────────
// ── Render Optimization Report ─────────────────────────────────
function renderOptimizationReport(report) {
  const card = document.getElementById('opt-report-card');
  if (!card || !report) return;
  const iters = report.iterations_run || 1;
  document.getElementById('opt-report-iters').textContent =
    `${iters} optimization pass${iters > 1 ? 'es' : ''}`;
  document.getElementById('opt-score-val').textContent =
    `+${report.score_improvement ?? 0}`;
  document.getElementById('opt-verbs-val').textContent   = report.action_verbs_count ?? 0;
  document.getElementById('opt-metrics-val').textContent = report.metrics_count ?? 0;
  document.getElementById('opt-kws-val').textContent     = report.keywords_injected ?? 0;
  document.getElementById('opt-skills-val').textContent  = report.total_skills ?? 0;
  document.getElementById('opt-projects-val').textContent = report.projects_rewritten ?? 0;

  const kwsEl = document.getElementById('opt-report-kws');
  if (report.keywords_list?.length) {
    kwsEl.innerHTML = `<span class="opt-kw-label">Keywords added:</span>` +
      report.keywords_list.map(k => `<span class="opt-kw-tag">${esc(k)}</span>`).join('');
    kwsEl.style.display = 'flex';
  }
  const secEl = document.getElementById('opt-report-sections');
  if (report.sections_improved?.length) {
    secEl.innerHTML = `<span class="opt-kw-label">Sections optimized:</span>` +
      report.sections_improved.map(s => `<span class="opt-section-tag">${esc(s)}</span>`).join('');
    secEl.style.display = 'flex';
  }
  card.style.display = 'block';
}

function renderComparison(cmp, originalScore, improvementNotes, isVerified) {
  const panel = document.getElementById('score-compare-panel');
  const loading = document.getElementById('compare-loading');
  if (!panel) return;

  loading.style.display = 'none';

  const improved  = cmp.improved_score ?? 0;
  const delta     = cmp.score_delta ?? (improved - originalScore);
  const deltaSign = delta >= 0 ? '+' : '';

  document.getElementById('compare-before-score').textContent = originalScore;
  document.getElementById('compare-after-score').textContent  = improved;

  const deltaEl = document.getElementById('compare-delta');
  deltaEl.textContent = `${deltaSign}${delta} pts`;
  deltaEl.className = 'compare-delta ' + (delta > 0 ? 'delta-positive' : delta < 0 ? 'delta-negative' : 'delta-neutral');

  // Verified badge
  const verifiedBadgeEl = document.getElementById('verified-score-badge');
  if (verifiedBadgeEl) {
    verifiedBadgeEl.style.display = isVerified ? 'inline-flex' : 'none';
  }

  // Confidence indicator
  const confEl = document.getElementById('score-confidence');
  if (confEl) {
    if (isVerified) {
      const variance = 3; // expected ±3 pts max
      confEl.innerHTML = `<span class="confidence-bar"><span class="confidence-fill" style="width:${Math.round((1 - variance/20)*100)}%"></span></span><span class="confidence-label">Score confidence: High (±${variance} pts expected variance)</span>`;
      confEl.style.display = 'flex';
    } else {
      confEl.style.display = 'none';
    }
  }

  // Show ATS badge if meaningful improvement
  if (delta >= 8) {
    document.getElementById('ats-optimized-badge').style.display = 'inline-flex';
  }

  // What improved
  document.getElementById('compare-what-improved').innerHTML =
    (cmp.what_improved || []).map(i => `<li>${esc(i)}</li>`).join('');

  // ATS applied
  document.getElementById('compare-ats-applied').innerHTML =
    (cmp.ats_optimization_applied || []).map(i => `<li>${esc(i)}</li>`).join('');

  // Still needs work
  document.getElementById('compare-still-needs').innerHTML =
    (cmp.what_still_needs_work || []).map(i => `<li>${esc(i)}</li>`).join('');

  // Summary
  const summaryEl = document.getElementById('compare-summary-text');
  summaryEl.textContent = cmp.comparison_summary || '';

  // Improvement notes from AI
  if (improvementNotes?.length) {
    const notesRow = document.getElementById('improvement-notes-row');
    const notesList = document.getElementById('improvement-notes-list');
    notesList.innerHTML = improvementNotes.map(n =>
      `<span class="improvement-note-tag">${esc(n)}</span>`).join('');
    notesRow.style.display = 'block';
  }

  panel.style.display = 'block';
}

// ── Render Improved Resume Preview ────────────────────────────────
function renderPreview(d) {
  let html = '';

  // Name + Contact
  html += `<div class="preview-name">${esc(d.candidate_name || 'Your Name')}</div>`;
  const c = d.contact || {};
  const contactParts = [c.email, c.phone, c.location, c.linkedin, c.github].filter(Boolean);
  if (contactParts.length) html += `<div class="preview-contact">${contactParts.map(esc).join('  |  ')}</div>`;

  // Summary
  if (d.professional_summary) {
    html += `<div class="preview-section-title">Professional Summary</div>`;
    html += `<p style="font-size:13.5px;margin-bottom:6px">${esc(d.professional_summary)}</p>`;
  }

  // Experience
  if (d.experience?.length) {
    html += `<div class="preview-section-title">Experience</div>`;
    for (const job of d.experience) {
      html += `<div class="preview-entry-title">${esc(job.title || '')}${job.company ? ' · ' + esc(job.company) : ''}</div>`;
      if (job.duration) html += `<div class="preview-entry-meta">${esc(job.duration)}</div>`;
      for (const b of (job.bullets || [])) html += `<div class="preview-bullet">${esc(b)}</div>`;
    }
  }

  // Education
  if (d.education?.length) {
    html += `<div class="preview-section-title">Education</div>`;
    for (const edu of d.education) {
      html += `<div class="preview-entry-title">${esc(edu.degree || '')}${edu.institution ? ' · ' + esc(edu.institution) : ''}</div>`;
      if (edu.duration) html += `<div class="preview-entry-meta">${esc(edu.duration)}</div>`;
      if (edu.details)  html += `<div class="preview-bullet">${esc(edu.details)}</div>`;
    }
  }

  // Skills
  const sk = d.skills || {};
  const skillLines = [
    { label: 'Languages',           val: sk.languages },
    { label: 'Frameworks & Libs',   val: sk.frameworks },
    { label: 'Tools & Platforms',   val: sk.tools },
    { label: 'Other',               val: sk.other },
  ].filter(s => s.val?.length);
  if (skillLines.length) {
    html += `<div class="preview-section-title">Technical Skills</div>`;
    for (const s of skillLines) {
      html += `<div class="preview-skill-line"><b>${s.label}:</b> ${s.val.map(esc).join(', ')}</div>`;
    }
  }

  // Projects
  if (d.projects?.length) {
    html += `<div class="preview-section-title">Projects</div>`;
    for (const proj of d.projects) {
      html += `<div class="preview-entry-title">${esc(proj.name || '')}${proj.tech ? ` <span style="color:var(--accent2);font-size:12px">(${esc(proj.tech)})</span>` : ''}</div>`;
      for (const b of (proj.bullets || [])) html += `<div class="preview-bullet">${esc(b)}</div>`;
    }
  }

  // Certifications
  if (d.certifications?.length) {
    html += `<div class="preview-section-title">Certifications</div>`;
    for (const cert of d.certifications) html += `<div class="preview-bullet">${esc(cert)}</div>`;
  }

  // Achievements
  if (d.achievements?.length) {
    html += `<div class="preview-section-title">Achievements</div>`;
    for (const ach of d.achievements) html += `<div class="preview-bullet">${esc(ach)}</div>`;
  }

  resumePreview.innerHTML = html;
}

function esc(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Generate Improved Resume ──────────────────────────────────────
improveBtn.addEventListener('click', async () => {
  if (!lastResumeText) {
    showNotification('❌ Please analyze a resume first before generating an improved version.', 'error');
    return;
  }

  improveBtn.disabled = true;
  startLoadingSteps('imp', ['imp-step-1','imp-step-2','imp-step-3'], improveLoadingOverlay);

  // Reset comparison panel state
  const comparePanel   = document.getElementById('score-compare-panel');
  const compareLoading = document.getElementById('compare-loading');
  if (comparePanel)   comparePanel.style.display = 'none';
  if (compareLoading) compareLoading.style.display = 'flex';
  document.getElementById('ats-optimized-badge').style.display = 'none';
  document.getElementById('improvement-notes-row').style.display = 'none';
  document.getElementById('opt-report-card').style.display     = 'none';
  document.getElementById('opt-report-kws').style.display      = 'none';
  document.getElementById('opt-report-sections').style.display = 'none';
  const verBadge = document.getElementById('verified-score-badge');
  if (verBadge) verBadge.style.display = 'none';
  const confEl2 = document.getElementById('score-confidence');
  if (confEl2) confEl2.style.display = 'none';

  const originalScore = lastAnalysisScore;
  const originalText  = lastResumeText;

  try {
    const resp = await fetch('/improve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resume_text:     originalText,
        original_score:  originalScore,
        score_breakdown: lastBreakdown,
        career_stage:    lastCareerStage,
      }),
    });

    let data = {};
    const contentType = resp.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      data = await resp.json();
    } else {
      const rawText = await resp.text();
      throw new Error(`Server returned HTTP ${resp.status}: ${rawText.substring(0, 150)}`);
    }

    stopLoadingSteps(improveLoadingOverlay);

    if (!resp.ok || data.error) {
      showNotification(`❌ ${data.error || 'Failed to generate improved resume.'}`, 'error');
      improveBtn.disabled = false; return;
    }

    lastImprovedText = data.improved_text || flattenImprovedData(data.improved_data);

    const improvementNotes   = data.improvement_notes || [];
    lastAtsOptimizations     = data.ats_optimizations_applied || improvementNotes || [];
    lastOptReport            = data.optimization_report || null;

    renderPreview(data.improved_data);
    downloadBtn.href = `/download/${data.pdf_filename}`;
    downloadBtn.download = 'improved_resume.pdf';
    improveModal.classList.remove('hidden');
    if (comparePanel) comparePanel.style.display = 'block';

    // Server ran verification using the same scoring engine as /analyze
    if (data.verified_score != null) {
      const verifCmp = {
        improved_score:           data.verified_score,
        score_delta:              data.verified_score - originalScore,
        score_breakdown:          data.verified_breakdown || {},
        sub_scores:               data.verified_sub_scores || {},
        what_improved:            data.what_improved || improvementNotes || [],
        what_still_needs_work:    data.what_still_needs_work || [],
        ats_optimization_applied: lastAtsOptimizations,
        comparison_summary: `This score was verified using the same engine as the main analyzer. Re-uploading the improved PDF should return ${data.verified_score} ±3 pts.`,
        scoring_engine:           'unified',
      };
      renderComparison(verifCmp, originalScore, improvementNotes, true);
      renderOptimizationReport(lastOptReport);
    } else {
      // Fallback: fire /compare
      fetch('/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ original_text: originalText, improved_text: lastImprovedText, original_score: originalScore }),
      })
      .then(r => r.json())
      .then(cmpData => {
        const isUnified = cmpData.comparison?.scoring_engine === 'unified';
        if (cmpData.success && cmpData.comparison) {
          const cmpWithAts = {
            ...cmpData.comparison,
            ats_optimization_applied: lastAtsOptimizations.length > 0
              ? lastAtsOptimizations
              : (cmpData.comparison.ats_optimization_applied || []),
          };
          renderComparison(cmpWithAts, originalScore, improvementNotes, isUnified);
          renderOptimizationReport(lastOptReport);
        } else {
          if (compareLoading) compareLoading.style.display = 'none';
          if (improvementNotes.length) renderComparison({}, originalScore, improvementNotes, false);
          else if (comparePanel) comparePanel.style.display = 'none';
        }
      })
      .catch(() => {
        if (compareLoading) compareLoading.style.display = 'none';
        if (comparePanel)   comparePanel.style.display = 'none';
      });
    }

  } catch (err) {
    stopLoadingSteps(improveLoadingOverlay);
    showNotification(`❌ Network error: ${err.message}`, 'error');
    improveBtn.disabled = false;
  }
});


// ── Modal Controls ────────────────────────────────────────────────
function closeModal() {
  improveModal.classList.add('hidden');
  improveBtn.disabled = false;
}
modalClose.addEventListener('click', closeModal);
improveModal.addEventListener('click', e => { if (e.target === improveModal) closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

// ── Hero Stat Counter Animation ───────────────────────────────────
function animateStatCounters() {
  document.querySelectorAll('.stat-number[data-target]').forEach(el => {
    const target   = parseInt(el.dataset.target, 10);
    const suffix   = el.dataset.suffix || '';
    const duration = 1400;
    const startTime = performance.now();
    function tick(now) {
      const elapsed  = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased    = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(eased * target) + suffix;
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });
}
document.addEventListener('DOMContentLoaded', animateStatCounters);

// ── Copy Content ──────────────────────────────────────────────────
copyBtn.addEventListener('click', async () => {
  const text = resumePreview.innerText || resumePreview.textContent;
  try {
    await navigator.clipboard.writeText(text);
    copyBtn.textContent = '✅ Copied!';
    setTimeout(() => { copyBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy Content`; }, 2000);
  } catch {
    showNotification('❌ Could not copy to clipboard.', 'error');
  }
});
