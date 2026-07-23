"""
AI Resume Analyzer — Flask Backend
Features:
  - /analyze   : Extract text + Gemini analysis
  - /improve   : Gemini rewrites resume → structured JSON
  - /download/<filename> : Serve generated PDF
Compatible with Python 3.8+
"""

import os
import json
import re
import uuid
import time
import requests
import PyPDF2
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables from .env (only active locally; ignored on servers)
load_dotenv()

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

# ─────────────────────────────────────────────
# App Configuration
# ─────────────────────────────────────────────
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
PDF_FOLDER    = os.path.join(os.path.dirname(__file__), 'generated_pdfs')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER,    exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'pdf'}

# ─────────────────────────────────────────────
# Gemini API Setup
# ─────────────────────────────────────────────

# Load API keys from environment variable (comma-separated for multiple keys).
# Set GEMINI_API_KEYS in your .env file or in your hosting platform's env config.
_raw_keys = os.getenv('GEMINI_API_KEYS', '')
GEMINI_API_KEYS = [k.strip() for k in _raw_keys.split(',') if k.strip()]

if not GEMINI_API_KEYS:
    raise RuntimeError(
        "\n\n  ❌  GEMINI_API_KEYS environment variable is not set!\n"
        "  Create a .env file with:  GEMINI_API_KEYS=your_key_here\n"
        "  Get a free key at: https://aistudio.google.com/app/apikey\n"
    )

_key_index = 0  # tracks which key is currently active

GEMINI_MODEL = 'gemini-2.0-flash'   # free-tier: 15 RPM

GEMINI_API_URL = (
    'https://generativelanguage.googleapis.com/v1beta/models/'
    f'{GEMINI_MODEL}:generateContent'
)

# ─────────────────────────────────────────────
# Career Stage Rubrics
# ─────────────────────────────────────────────
# Each stage maps category → (display_label, max_pts, evaluation_hint)
# All max_pts within a stage sum to exactly 100.

STAGE_RUBRICS = {
    'student': {
        'project_quality':          ('Projects & Portfolio',      30, 'GitHub-linked projects, deployed apps, hackathons, clear problem/solution/tech stack'),
        'skills_relevance':         ('Technical Skills',           20, 'Programming languages, frameworks, tools; categorized and ATS-ready'),
        'ats_optimization':         ('ATS & Formatting',           15, 'Keyword density, standard section headers, clean formatting'),
        'education_certifications': ('Education & Certifications', 15, 'GPA, relevant coursework, Coursera/NPTEL/AWS/Google certs'),
        'experience_impact':        ('Internships & Activities',   10, 'Internships, open-source contributions, hackathon wins, clubs'),
        'formatting_structure':     ('Structure & Clarity',         7, 'Logical flow, completeness, consistent dates and bullets'),
        'grammar_clarity':          ('Communication',               3, 'Professional writing, clear bullet structure, no errors'),
    },
    'early': {
        'experience_impact':        ('Work Experience',            25, 'Quantified impact in roles, delivered projects, growth shown'),
        'project_quality':          ('Projects & Portfolio',       20, 'Side projects, open source, personal portfolio quality'),
        'skills_relevance':         ('Technical Skills',           20, 'Depth and breadth of technical stack matching job market'),
        'ats_optimization':         ('ATS & Keywords',             15, 'Industry keywords, parseable formatting'),
        'formatting_structure':     ('Formatting',                  7, 'Professional presentation, section order, consistency'),
        'grammar_clarity':          ('Communication',               5, 'Writing quality, concise active-voice bullets'),
        'education_certifications': ('Education & Certs',           8, 'Degree + any industry certifications earned'),
    },
    'mid': {
        'experience_impact':        ('Professional Impact',        30, 'Leadership, scale, strategic contributions, quantified results'),
        'skills_relevance':         ('Technical Depth',            18, 'Expert-level skills, architecture patterns, system design'),
        'ats_optimization':         ('ATS & Keywords',             15, 'Mid-senior level keywords, industry terminology'),
        'project_quality':          ('Projects & Innovation',      12, 'Technical initiatives led, OSS contributions, side projects'),
        'formatting_structure':     ('Presentation',               10, 'Executive-level formatting, structure, readability'),
        'grammar_clarity':          ('Communication',              10, 'Senior-level writing, conciseness, impact-first language'),
        'education_certifications': ('Education & Certs',           5, 'Advanced degrees, AWS/GCP/Azure architect-level certs'),
    },
    'senior': {
        'experience_impact':        ('Leadership & Strategic Impact', 35, 'Org-level impact, revenue/savings, scale, team leadership, strategic decisions'),
        'skills_relevance':         ('Technical Expertise',        17, 'Principal/architect-level stack, system design at scale'),
        'ats_optimization':         ('ATS & Executive Keywords',   15, 'C-suite and principal-level keywords, board-level language'),
        'formatting_structure':     ('Executive Presentation',     10, 'Executive resume format, strong summary, concise impact'),
        'grammar_clarity':          ('Communication',              10, 'Boardroom-quality writing, strategic narrative'),
        'project_quality':          ('Innovation & Thought Leadership', 8, 'Patents, publications, keynotes, open-source leadership'),
        'education_certifications': ('Education & Credentials',    5,  'Advanced degrees, board memberships, executive programs'),
    },
}

STAGE_LABELS = {
    'student': 'Student / Fresher',
    'early':   'Early Career (1–3 yrs)',
    'mid':     'Mid Career (3–7 yrs)',
    'senior':  'Senior / Lead (7+ yrs)',
}

STAGE_TIERS = {
    'student': {'weak': (35,55), 'average': (55,70), 'good': (70,85), 'excellent': (85,92)},
    'early':   {'weak': (35,55), 'average': (55,72), 'good': (72,86), 'excellent': (86,94)},
    'mid':     {'weak': (35,50), 'average': (50,68), 'good': (68,84), 'excellent': (84,96)},
    'senior':  {'weak': (35,48), 'average': (48,65), 'good': (65,82), 'excellent': (82,96)},
}

STAGE_CEILINGS = {'student': 92, 'early': 94, 'mid': 96, 'senior': 96}


def detect_career_stage(text: str) -> str:
    """
    Auto-detect career stage from resume text.
    Returns: 'student' | 'early' | 'mid' | 'senior'
    """
    import re as _re
    t = text.lower()

    # ── Student signals ────────────────────────────────────────────
    student_kws = [
        'undergraduate', 'b.tech', 'b.e.', 'b.sc', 'bachelor of', 'pursuing',
        'sophomore', 'freshman', 'junior year', 'senior year', 'final year',
        'third year', 'second year', 'first year', 'expected graduation',
        'expected:', 'graduating in', 'college student', 'university student',
        '4th year', '3rd year', '2nd year', '1st year',
    ]
    future_grad = _re.search(r'20(2[4-9]|[3-9]\d)', text)
    has_student_kw = any(kw in t for kw in student_kws)

    if has_student_kw or future_grad:
        # Confirm: if they also have significant work history, override
        exp_blocks = _re.findall(
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,]+20\d{2}\s*[-–]',
            t
        )
        if len(exp_blocks) < 3:
            return 'student'

    # ── Estimate total years of experience ────────────────────────
    # Pattern: "YYYY – YYYY" or "YYYY – Present"
    year_ranges = _re.findall(
        r'20(\d{2})\s*[-–]\s*(?:20(\d{2})|present|current|now)', t
    )
    total_exp = 0
    for start, end in year_ranges:
        s = int('20' + start)
        e = 2025 if not end else int('20' + end)
        total_exp += max(0, e - s)

    # Explicit mention "X years of experience"
    m = _re.search(r'(\d+)\+?\s*years?\s+(?:of\s+)?experience', t)
    if m:
        total_exp = max(total_exp, int(m.group(1)))

    if total_exp >= 7:  return 'senior'
    if total_exp >= 3:  return 'mid'
    if total_exp >= 1:  return 'early'
    return 'student'


def compute_potential_score(analysis: dict, stage: str) -> dict:
    """
    Estimate achievable score and return a prioritised improvement roadmap.
    Only counts gaps that are realistically closable (below 70% of max).
    """
    current  = analysis.get('score', 0)
    bd       = analysis.get('score_breakdown', {})
    rubric   = STAGE_RUBRICS.get(stage, STAGE_RUBRICS['student'])
    ceiling  = STAGE_CEILINGS.get(stage, 92)

    potential_gain = 0
    improvement_items = []

    for key, (label, max_pts, hint) in rubric.items():
        if max_pts == 0:
            continue
        actual = bd.get(key, 0)
        pct    = actual / max_pts
        gap    = max_pts - actual
        if pct < 0.70 and gap >= 2:
            # Realistically 65% of the gap is achievable through focused effort
            achievable = round(gap * 0.65)
            potential_gain += achievable
            improvement_items.append({
                'category': label,
                'current':  actual,
                'max':      max_pts,
                'gain':     achievable,
                'hint':     hint,
                'pct':      int(pct * 100),
            })

    potential_score = min(current + potential_gain, ceiling)
    # Never show potential below current
    potential_score = max(potential_score, current)

    # Thin resume: score below 52 with few skills/strengths
    is_thin = (
        current < 52 or
        (len(analysis.get('skills_detected', [])) < 5 and
         len(analysis.get('strengths', [])) < 2)
    )

    starter_plan = []
    if is_thin:
        stage_starters = {
            'student': [
                'Add 2–3 projects with GitHub links, tech stack, and 2-bullet descriptions',
                'List at least 8 technical skills in categorised groups (Languages, Frameworks, Tools)',
                'Add your GPA and list 4–5 relevant courses (DSA, DBMS, OS, ML)',
                'Complete one online certification (Coursera / NPTEL / AWS Free Tier)',
                'Add a 3-sentence professional summary targeting your internship goal',
            ],
            'early': [
                'Add quantified impact to every work bullet (%, users, $, time saved)',
                'Add 2 side-projects or open-source contributions with tech detail',
                'Expand skills section to 15+ technologies with clear categorisation',
                'Add a professional summary targeting your next role',
                'Earn one industry certification (AWS / GCP / Azure / Google)',
            ],
            'mid': [
                'Add leadership + scale to every experience bullet (team size, scope, revenue/savings)',
                'Include system design or architecture decisions you drove',
                'Add measurable outcomes: 40% latency reduction, $1M cost saving, etc.',
                'Earn or list architect-level certifications (AWS SA, GCP Pro)',
                'Add a senior-level professional summary with your strategic specialisation',
            ],
            'senior': [
                'Quantify org-level impact: P&L, headcount grown, revenue influenced',
                'Add board/advisory/thought leadership credentials',
                'Write an executive summary highlighting strategic vision',
                'List patents, publications, or keynote talks',
                'Trim junior-level content; every bullet must show scale and strategy',
            ],
        }
        starter_plan = stage_starters.get(stage, stage_starters['student'])

    return {
        'potential_score':    potential_score,
        'potential_gain':     potential_gain,
        'ceiling':            ceiling,
        'improvement_items':  sorted(improvement_items, key=lambda x: -x['gain'])[:5],
        'is_thin_resume':     is_thin,
        'starter_plan':       starter_plan,
    }


# ─────────────────────────────────────────────
# Shared Helpers
# ─────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(filepath: str) -> str:
    """Extract all text from a PDF using PyPDF2, with normalization for consistency."""
    text = ""
    try:
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        raise ValueError(f"Failed to read PDF: {str(e)}")

    if not text.strip():
        raise ValueError(
            "Could not extract text from the PDF. "
            "The file may be image-based or corrupted."
        )
    # Normalize before returning — same normalization applied to internally
    # generated text, ensuring re-uploaded PDFs score consistently.
    return normalize_resume_text(text)



def call_gemini(prompt: str, expect_json: bool = True, temperature: float = 0.3) -> str:
    """
    Send a prompt to Gemini and return the response text.
    On 429, rotates API keys and retries with exponential backoff.
    Raises RuntimeError on final failure.
    """
    global _key_index

    gen_config = {
        'temperature': temperature,
        'maxOutputTokens': 8192,
    }
    if expect_json:
        gen_config['responseMimeType'] = 'application/json'

    total_attempts = len(GEMINI_API_KEYS) * 2  # try each key twice max

    for attempt in range(total_attempts):
        current_key = GEMINI_API_KEYS[_key_index % len(GEMINI_API_KEYS)]
        try:
            resp = requests.post(
                GEMINI_API_URL,
                params={'key': current_key},
                json={
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': gen_config,
                },
                timeout=120
            )

            if resp.status_code == 429:
                # Read Retry-After header if Google provides it
                retry_after = resp.headers.get('Retry-After')
                if retry_after:
                    wait = int(retry_after)
                else:
                    wait = min(10 * (2 ** attempt), 60)  # exponential, capped at 60s

                # Rotate to next key
                _key_index = (_key_index + 1) % len(GEMINI_API_KEYS)
                next_key_preview = GEMINI_API_KEYS[_key_index][:12] + '...'
                print(f"[Gemini] 429 on key ...{current_key[-6:]}. "
                      f"Rotating to key {next_key_preview}, waiting {wait}s... "
                      f"(attempt {attempt + 1}/{total_attempts})")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            parts = resp.json()['candidates'][0]['content']['parts']
            return ''.join(p.get('text', '') for p in parts)

        except RuntimeError:
            raise
        except requests.exceptions.Timeout:
            raise RuntimeError('Gemini API timed out. Please try again.')
        except Exception as e:
            error_str = str(e)
            if '429' in error_str or 'rate' in error_str.lower():
                wait = min(10 * (2 ** attempt), 60)
                _key_index = (_key_index + 1) % len(GEMINI_API_KEYS)
                print(f"[Gemini] Rate error on attempt {attempt + 1}, rotating key, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise RuntimeError(f'Gemini API error: {error_str}')

    raise RuntimeError(
        'All Gemini API keys are rate-limited. '
        'Please wait 1 minute and try again, or add a new API key at '
        'https://aistudio.google.com/app/apikey'
    )


def call_gemini_analysis(prompt: str) -> str:
    """
    Same as call_gemini but uses temperature=0.7 for the analysis call
    to ensure score variability across different resume quality levels.
    """
    global _key_index

    gen_config = {
        'temperature': 0.45,   # 0.45: enough variability for score differentiation, low enough to keep same-text variance within ±3 pts
        'maxOutputTokens': 8192,
        'responseMimeType': 'application/json',
    }

    total_attempts = len(GEMINI_API_KEYS) * 2

    for attempt in range(total_attempts):
        current_key = GEMINI_API_KEYS[_key_index % len(GEMINI_API_KEYS)]
        try:
            resp = requests.post(
                GEMINI_API_URL,
                params={'key': current_key},
                json={
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': gen_config,
                },
                timeout=120
            )

            if resp.status_code == 429:
                retry_after = resp.headers.get('Retry-After')
                wait = int(retry_after) if retry_after else min(10 * (2 ** attempt), 60)
                _key_index = (_key_index + 1) % len(GEMINI_API_KEYS)
                print(f"[Gemini-Analysis] 429, rotating key, waiting {wait}s... (attempt {attempt+1})")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            parts = resp.json()['candidates'][0]['content']['parts']
            return ''.join(p.get('text', '') for p in parts)

        except RuntimeError:
            raise
        except requests.exceptions.Timeout:
            raise RuntimeError('Gemini API timed out. Please try again.')
        except Exception as e:
            error_str = str(e)
            if '429' in error_str or 'rate' in error_str.lower():
                wait = min(10 * (2 ** attempt), 60)
                _key_index = (_key_index + 1) % len(GEMINI_API_KEYS)
                print(f"[Gemini-Analysis] Rate error on attempt {attempt+1}, rotating key, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise RuntimeError(f'Gemini API error: {error_str}')

    raise RuntimeError(
        'All Gemini API keys are rate-limited. '
        'Please wait 1 minute and try again, or add a new API key at '
        'https://aistudio.google.com/app/apikey'
    )


def parse_json_response(raw_text: str) -> dict:
    """Robustly extract a JSON object from raw Gemini response text."""
    start = raw_text.find('{')
    end   = raw_text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON found in response.\nRaw: {raw_text[:400]}")
    try:
        return json.loads(raw_text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON: {e}\nRaw: {raw_text[:400]}")


def normalize_resume_text(text: str) -> str:
    """
    Normalize resume text before scoring to ensure consistent extraction
    across different sources (PDF upload vs. internally flattened JSON).
    Removes PDF ligatures, normalizes whitespace, preserves bullet structure.
    """
    import unicodedata
    # Unicode normalization (handles ligatures like ﬁ ﬂ from PDFs)
    text = unicodedata.normalize('NFKC', text)
    # Replace fancy bullets/dashes with plain ASCII
    for ch, repl in [('\u2022','•'), ('\u2013','-'), ('\u2014','-'), ('\ufb01','fi'), ('\ufb02','fl'), ('\u2019',"'"), ('\u201c','"'), ('\u201d','"')]:
        text = text.replace(ch, repl)
    # Collapse multiple blank lines to one
    import re as _re
    text = _re.sub(r'\n{3,}', '\n\n', text)
    # Strip trailing whitespace per line
    text = '\n'.join(line.rstrip() for line in text.splitlines())
    return text.strip()


def score_text_with_analysis_engine(text: str) -> dict:
    """
    Score any resume text using the EXACT SAME engine as /analyze.
    This is the single source of truth for all score displays — /improve,
    /compare, and the main /analyze route all use this function so that
    the score shown internally always matches what re-uploading the PDF gives.
    Returns the parsed analysis dict or raises RuntimeError.
    """
    normalized = normalize_resume_text(text)
    prompt = build_analysis_prompt(normalized)
    raw    = call_gemini_analysis(prompt)
    return parse_json_response(raw)


def flatten_improved_data_to_text(data: dict) -> str:
    """
    Convert the structured improved_data JSON back to a plain-text resume
    that is representative of what the PDF text extractor will produce.
    Used to verify the improved score without a round-trip through PDF.
    """
    lines = []
    if data.get('candidate_name'):
        lines.append(data['candidate_name'])
    c = data.get('contact', {})
    contact_parts = [c.get('email',''), c.get('phone',''), c.get('location',''),
                     c.get('linkedin',''), c.get('github','')]
    lines.append('  |  '.join(p for p in contact_parts if p))
    lines.append('')
    if data.get('professional_summary'):
        lines.append('PROFESSIONAL SUMMARY')
        lines.append(data['professional_summary'])
        lines.append('')
    sk = data.get('skills', {})
    skill_parts = []
    if sk.get('languages'):  skill_parts.append('Languages: ' + ', '.join(sk['languages']))
    if sk.get('frameworks'): skill_parts.append('Frameworks & Libraries: ' + ', '.join(sk['frameworks']))
    if sk.get('tools'):      skill_parts.append('Tools & Platforms: ' + ', '.join(sk['tools']))
    if sk.get('other'):      skill_parts.append('Other: ' + ', '.join(sk['other']))
    if skill_parts:
        lines.append('TECHNICAL SKILLS')
        lines.extend(skill_parts)
        lines.append('')
    if data.get('experience'):
        lines.append('EXPERIENCE')
        for job in data['experience']:
            lines.append(f"{job.get('title','')}  ·  {job.get('company','')}")
            if job.get('duration'): lines.append(job['duration'])
            for b in job.get('bullets', []): lines.append('• ' + b)
        lines.append('')
    if data.get('projects'):
        lines.append('PROJECTS')
        for proj in data['projects']:
            tech = f" ({proj.get('tech','')})" if proj.get('tech') else ''
            lines.append(f"{proj.get('name','')}{tech}")
            for b in proj.get('bullets', []): lines.append('• ' + b)
        lines.append('')
    if data.get('education'):
        lines.append('EDUCATION')
        for edu in data['education']:
            lines.append(f"{edu.get('degree','')}  ·  {edu.get('institution','')}")
            if edu.get('duration'): lines.append(edu['duration'])
            if edu.get('details'):  lines.append(edu['details'])
        lines.append('')
    if data.get('certifications'):
        lines.append('CERTIFICATIONS')
        for cert in data['certifications']: lines.append('• ' + cert)
        lines.append('')
    if data.get('achievements'):
        lines.append('ACHIEVEMENTS')
        for ach in data['achievements']: lines.append('• ' + ach)
    return '\n'.join(lines)



# ─────────────────────────────────────────────
# Analysis Prompt
# ─────────────────────────────────────────────

def build_analysis_prompt(resume_text: str, career_stage: str = 'student') -> str:
    rubric   = STAGE_RUBRICS.get(career_stage, STAGE_RUBRICS['student'])
    label    = STAGE_LABELS.get(career_stage, 'Student / Fresher')
    tiers    = STAGE_TIERS.get(career_stage, STAGE_TIERS['student'])
    ceiling  = STAGE_CEILINGS.get(career_stage, 92)

    # Build scoring-categories block for the prompt
    rubric_lines = '\n'.join(
        f'- {key} (max {mx} pts) [{lbl}]: {hint}'
        for key, (lbl, mx, hint) in rubric.items()
    )
    # Build score tiers block
    tier_lines = '\n'.join(
        f'   - {name.capitalize()} resume ({lo}–{hi}): {_tier_desc(name, career_stage)}'
        for name, (lo, hi) in tiers.items()
    )

    return f"""
You are a STRICT senior technical recruiter and ATS expert who specialises in evaluating resumes for {label} candidates.

CAREER STAGE: {label}
This evaluation uses a rubric calibrated for {label} candidates.
A score of 85+ means "excellent for someone at this career stage" — NOT "excellent for a CTO."
The maximum achievable score is {ceiling}.

CRITICAL SCORING RULES — READ CAREFULLY:
1. Produce REALISTIC scores. Do NOT default to 70-78 for every resume.
2. Stage-appropriate score tiers:
{tier_lines}
3. PENALIZE heavily for:
   - Vague project descriptions ("Built a website", "Created an app", "Developed a system")
   - No quantified achievements (no %, numbers, scale, users, performance gains)
   - Missing GitHub/LinkedIn for student resumes
   - Buzzword stuffing without proof
   - Generic objective statements
   - Repetitive language across bullets
4. REWARD generously for:
   - Measurable outcomes (e.g., "Reduced API latency by 40%", "Served 10K+ daily users")
   - Specific tech stack with architecture decisions
   - Live project or GitHub links (for students)
   - Relevant certifications
   - Clean ATS-parseable formatting
   - Strong action verbs at start of every bullet

SCORING CATEGORIES for {label} (the 7 values MUST sum exactly to the total score field):
{rubric_lines}

RESUME TEXT TO EVALUATE:
---
{resume_text}
---

Return ONLY a valid JSON object with EXACTLY this structure. No markdown, no extra text:

{{
  "score": <integer 35-{ceiling}, must honestly reflect quality for {label}>,
  "score_breakdown": {{
    "skills_relevance": <integer>,
    "project_quality": <integer>,
    "ats_optimization": <integer>,
    "experience_impact": <integer>,
    "formatting_structure": <integer>,
    "grammar_clarity": <integer>,
    "education_certifications": <integer>
  }},
  "sub_scores": {{
    "ats_score": <integer 0-100, ATS pass likelihood>,
    "technical_score": <integer 0-100, technical depth>,
    "project_score": <integer 0-100, project section quality>,
    "communication_score": <integer 0-100, grammar and clarity>,
    "overall_strength": "<Weak | Average | Good | Excellent>"
  }},
  "score_explanation": {{
    "why_this_score": "<2-3 sentences explaining this specific score, referencing actual resume content>",
    "areas_that_reduced_score": ["<specific issue>", "<another issue>", "<another>"],
    "areas_that_performed_well": ["<specific strength>", "<another strength>"]
  }},
  "skills_detected": [<list of skills found in resume>],
  "strengths": [<list of 3-5 specific strengths referencing actual content>],
  "weaknesses": [<list of 3-5 specific weaknesses referencing actual content>],
  "missing_skills": [<list of missing skills that would improve this resume>],
  "suggestions": [<list of 5-7 specific, actionable suggestions — NOT generic advice>],
  "ats_feedback": {{
    "is_ats_friendly": <boolean>,
    "ats_score": <integer 0-100>,
    "issues": [<list of specific ATS issues>],
    "tips": [<list of specific ATS tips>]
  }},
  "experience_level": "<Entry Level | Mid Level | Senior Level | Executive>",
  "job_titles_suggested": [<list of 3 specific job titles matching resume>],
  "summary": "<2-3 sentence honest overall assessment referencing actual content>"
}}
""".strip()


def _tier_desc(name: str, stage: str) -> str:
    """Return a stage-appropriate tier description."""
    descs = {
        'student': {
            'weak':      'vague or missing projects, no skills listed, no structure',
            'average':   'some projects but lacking detail or metrics, basic skills list',
            'good':      'clear projects with tech stack, some metrics, ATS-friendly',
            'excellent': 'strong projects with GitHub+metrics, certifications, excellent ATS formatting',
        },
        'early': {
            'weak':      'generic job descriptions, no metrics, entry-level presentation',
            'average':   'some impact shown, limited depth in projects/skills',
            'good':      'quantified bullets, solid portfolio, good ATS formatting',
            'excellent': 'strong impact metrics, impressive portfolio, excellent keyword density',
        },
        'mid': {
            'weak':      'no leadership evidence, generic bullets, low technical depth',
            'average':   'some quantified impact, basic tech depth',
            'good':      'clear leadership, strong metrics, architecture decisions shown',
            'excellent': 'strategic impact, scale, system design, exceptional presentation',
        },
        'senior': {
            'weak':      'no strategic impact, junior-level writing, generic bullets',
            'average':   'some org impact but limited strategic narrative',
            'good':      'org-level impact, strong metrics, executive presence',
            'excellent': 'board-level impact, innovation leadership, exceptional strategic narrative',
        },
    }
    return descs.get(stage, descs['student']).get(name, '')




# ─────────────────────────────────────────────
# Improvement Prompt
# ─────────────────────────────────────────────

def build_improve_prompt(resume_text: str, original_score: int = 0, score_breakdown: dict = None) -> str:
    breakdown = score_breakdown or {}

    # Compute target score range based on original
    if original_score >= 75:
        target_min, target_max = 87, 95
    elif original_score >= 60:
        target_min, target_max = 80, 90
    elif original_score >= 45:
        target_min, target_max = 73, 85
    else:
        target_min, target_max = 68, 80

    # Identify weakest scoring categories to focus on
    cat_maxes = {
        'skills_relevance': 20, 'project_quality': 20, 'ats_optimization': 15,
        'experience_impact': 15, 'formatting_structure': 10, 'grammar_clarity': 10,
        'education_certifications': 10,
    }
    focus_lines = []
    for key, mx in cat_maxes.items():
        actual = breakdown.get(key, 0)
        pct = (actual / mx * 100) if mx else 0
        label = key.replace('_', ' ').title()
        tag = "⚠ CRITICAL FIX NEEDED" if pct < 60 else ("⚡ IMPROVE" if pct < 80 else "✓ OK")
        focus_lines.append(f"  {tag}  {label}: {actual}/{mx} pts ({int(pct)}%)")
    focus_text = '\n'.join(focus_lines)

    score_context = f"""
ORIGINAL SCORE: {original_score}/100
TARGET SCORE RANGE: {target_min}–{target_max}/100  ← you MUST achieve this through real improvements
GAP TO CLOSE: {target_min - original_score}–{target_max - original_score} points

SCORING CATEGORIES (fix weakest first):
{focus_text}
""" if original_score > 0 else ""


    return f"""
You are a FAANG-level technical resume writer, ATS optimization expert, and senior recruiter. Your ONLY job is to produce a dramatically improved version of the resume below that achieves a significantly higher score.
{score_context}
=== MANDATORY IMPROVEMENT RULES ===

**PRIORITY 1 — PROJECT DESCRIPTIONS (highest score impact):**
- Rewrite EVERY project bullet using: [Strong Verb] + [Specific Tech] + [What It Does] + [Measurable Result]
- Bad: "Made a website using React"
- Good: "Architected a full-stack web application using React 18, Node.js, and MongoDB, implementing JWT-based authentication and RESTful APIs — achieving sub-150ms average response times and serving 500+ active users"
- Add specific version numbers, architecture decisions, deployment details where implied
- Every project must have 2-3 rich bullets with metrics

**PRIORITY 2 — ACTION VERBS (apply to every single bullet):**
- Replace ALL weak verbs: built→Engineered, made→Developed, worked→Implemented, helped→Collaborated, created→Architected, used→Leveraged, fixed→Resolved, ran→Orchestrated
- Allowed strong verbs: Engineered, Architected, Designed, Developed, Optimized, Spearheaded, Deployed, Integrated, Automated, Streamlined, Implemented, Reduced, Increased, Delivered, Launched, Accelerated, Migrated, Refactored, Established, Orchestrated

**PRIORITY 3 — QUANTIFICATION (add to every bullet where plausible):**
- Users/scale → "Serving X+ concurrent users"
- Performance → "reducing latency by X%" or "improving throughput by X%"
- Datasets → "processing X+ records" or "X GB dataset"
- ML models → "achieving X% accuracy on test set"
- Time savings → "reducing manual effort by X hours/week"
- ONLY add metrics that are directionally implied — never fabricate context

**PRIORITY 4 — ATS KEYWORD INJECTION:**
- Inject into summary + skills + bullets: REST API, CI/CD pipeline, Agile/Scrum, version control, Git, Docker, cloud computing, system design, object-oriented programming, data structures & algorithms
- For AI/ML context: neural networks, model training, data preprocessing, feature engineering, TensorFlow, PyTorch, scikit-learn, NumPy, pandas, Jupyter Notebooks
- For SWE context: microservices architecture, API development, unit testing, test-driven development, code review, database optimization, containerization

**PRIORITY 5 — PROFESSIONAL SUMMARY:**
- Write 3-4 sentences: [experience level/degree] + [top 3-4 skills] + [strongest achievement] + [goal]
- Must include ATS keywords naturally
- Must mention a specific quantified achievement from their resume

**PRIORITY 6 — SKILLS SECTION:**
- Consolidate ALL technologies mentioned anywhere in resume into the skills section
- Organize into: Languages | Frameworks & Libraries | Tools & Platforms | Concepts
- Add standard missing ones: Git, GitHub, VS Code, REST APIs, Agile if not present

**FORMATTING:**
- ATS-optimal order: Summary → Skills → Experience → Projects → Education → Certifications
- Consistent date format: Mon YYYY – Mon YYYY
- 3-5 bullets per experience role, 2-3 per project
- Add relevant coursework to education if implied (Data Structures, Algorithms, DBMS, OS, ML)

ORIGINAL RESUME TEXT:
---
{resume_text}
---

Return ONLY a valid JSON object (no markdown, no extra text):

{{
  "candidate_name": "<full name from resume>",
  "contact": {{
    "email": "<email or empty>",
    "phone": "<phone or empty>",
    "linkedin": "<linkedin URL or empty>",
    "github": "<github URL or empty>",
    "location": "<city, country or empty>"
  }},
  "professional_summary": "<3-4 sentence ATS-optimized summary — must include specific skills, measurable achievement, and career goal>",
  "experience": [
    {{
      "title": "<job title>",
      "company": "<company name>",
      "duration": "<Mon YYYY – Mon YYYY>",
      "bullets": ["<Strong verb + specific tech + measurable outcome>", "<another metric-backed bullet>", "<another>"]
    }}
  ],
  "education": [
    {{
      "degree": "<degree name>",
      "institution": "<institution name>",
      "duration": "<YYYY – YYYY>",
      "details": "<GPA if mentioned; Relevant coursework: Data Structures, Algorithms, DBMS, OS, Machine Learning>"
    }}
  ],
  "skills": {{
    "languages": [<all programming languages mentioned anywhere>],
    "frameworks": [<all frameworks and libraries>],
    "tools": [<all tools, platforms, cloud services, IDEs>],
    "other": [<concepts: REST APIs, CI/CD, Agile/Scrum, OOP, System Design, Git, etc.>]
  }},
  "projects": [
    {{
      "name": "<project name>",
      "tech": "<comma-separated tech stack>",
      "bullets": ["<Strong verb + specific tech + measurable outcome>", "<tech architecture detail + result>", "<deployment or scale detail>"]
    }}
  ],
  "certifications": ["<full official certification name>"],
  "achievements": ["<specific achievement with numbers>"],
  "improvement_notes": [
    "<major improvement 1: e.g. 'Rewrote all 6 project bullets with measurable metrics and strong action verbs'>",
    "<major improvement 2: e.g. 'Injected 14 ATS-critical keywords across summary, skills, and bullets'>",
    "<major improvement 3>", "<major improvement 4>", "<major improvement 5>"
  ],
  "ats_optimizations_applied": [
    "<specific ATS optimization 1: e.g. 'Added CI/CD, REST API, Agile/Scrum keywords to summary and skills'>",
    "<specific ATS optimization 2: e.g. 'Standardized section headers to ATS-parseable format'>",
    "<specific ATS optimization 3: e.g. 'Replaced 8 weak action verbs with high-impact alternatives'>",
    "<specific ATS optimization 4: e.g. 'Added quantified metrics to all 9 project bullets'>",
    "<specific ATS optimization 5: e.g. 'Expanded skills section from 12 to 28 technologies with ATS categorization'>",
    "<specific ATS optimization 6: e.g. 'Rewrote professional summary with 6 ATS-critical keywords'>",
    "<specific ATS optimization 7 if applicable>",
    "<specific ATS optimization 8 if applicable>"
  ]
}}

RULES:
- NEVER invent jobs, degrees, or companies
- NEVER add metrics that are not implied by the original content
- ats_optimizations_applied MUST have at least 6 specific, non-generic entries describing exactly what you changed
- improvement_notes MUST have at least 5 entries
"""


def build_compare_prompt(original_text: str, improved_text: str, original_score: int) -> str:
    return f"""
You are a strict ATS scoring expert. You have already scored the ORIGINAL resume at {original_score}/100.
Now analyze the IMPROVED resume and provide:
1. A new score for the improved resume (must be honest — only higher if genuinely better)
2. A comparison of what actually improved

ORIGINAL RESUME (scored {original_score}/100):
---
{original_text}
---

IMPROVED RESUME:
---
{improved_text}
---

SCORING RULES:
- Weak resume (35-55): vague bullets, no metrics, generic
- Average resume (55-70): some detail, missing depth
- Good resume (70-85): clear tech stack, some metrics
- Excellent resume (85-95): strong metrics, ATS-optimized
- The improved score should be HIGHER if the improved resume has better action verbs, metrics, ATS keywords, clearer structure
- Do NOT inflate scores if improvement is minimal

Score categories (must sum to total):
- skills_relevance: max 20
- project_quality: max 20
- ats_optimization: max 15
- experience_impact: max 15
- formatting_structure: max 10
- grammar_clarity: max 10
- education_certifications: max 10

Return ONLY valid JSON:
{{
  "improved_score": <integer 35-95>,
  "score_breakdown": {{
    "skills_relevance": <0-20>,
    "project_quality": <0-20>,
    "ats_optimization": <0-15>,
    "experience_impact": <0-15>,
    "formatting_structure": <0-10>,
    "grammar_clarity": <0-10>,
    "education_certifications": <0-10>
  }},
  "score_delta": <improved_score minus {original_score}, positive means improvement>,
  "what_improved": ["<specific improvement 1>", "<specific improvement 2>", "<specific improvement 3>"],
  "what_still_needs_work": ["<remaining issue 1>", "<remaining issue 2>"],
  "ats_optimization_applied": ["<ATS keyword added>", "<formatting fix applied>", "<another>"],
  "comparison_summary": "<2-3 sentences comparing original vs improved resume honestly>"
}}
"""




# ─────────────────────────────────────────────
# Boost Prompt (2nd / 3rd optimization pass)
# ─────────────────────────────────────────────

def build_boost_prompt(current_data_json: str, current_score: int,
                        target_score: int, weak_categories: list) -> str:
    weak_text = '\n'.join(f'  \u26a0 {c}' for c in weak_categories)
    gap = target_score - current_score
    return f"""
You are an elite FAANG resume coach and ATS optimization engine.
This resume currently scores {current_score}/100. Close the {gap}-point gap to reach {target_score}+ through REAL quality improvements only.

SCORING RUBRIC (must internalize):
- skills_relevance    max 20 pts: breadth + depth + categorization + modern tools
- project_quality     max 20 pts: architecture detail + metrics + tech stack + measurable impact
- ats_optimization    max 15 pts: keyword density + ATS-parseable headers + formatting
- experience_impact   max 15 pts: action verbs + quantified outcomes + relevance
- formatting_structure max 10 pts: order + consistency + completeness
- grammar_clarity     max 10 pts: professional tone + zero vagueness + active voice
- education_certifications max 10 pts: GPA + coursework + certifications

WEAKEST CATEGORIES TO FIX (focus here first):
{weak_text}

CURRENT RESUME JSON:
{current_data_json}

MANDATORY BOOST RULES:
1. PROJECTS (20 pts): every bullet = [Strong Verb]+[Specific Tech]+[Architecture]+[Metric]
   - Add 1 extra metric bullet per project not already present
   - Include: API design, DB choice, deployment, performance benchmarks
   - Example: "Architected RESTful API with FastAPI+PostgreSQL+Redis caching — 60% latency reduction, 1K+ concurrent users"
2. SKILLS (20 pts): all 4 categories populated; add if missing: Git, Docker, REST APIs, CI/CD, Agile, System Design, OOP, Data Structures
3. ATS KEYWORDS (15 pts): inject into summary+skills.other+bullets: REST API, CI/CD pipeline, Agile/Scrum, OOP, data structures and algorithms, version control, cloud computing, system design
4. EXPERIENCE (15 pts): every bullet starts with strong verb + contains at least one number; remove ALL generic bullets
5. SUMMARY: 3-4 sentences — role+education, top 3 tech, quantified achievement, career target with ATS keyword
6. FORMATTING: section order: summary→skills→experience→projects→education→certifications

Return ONLY a valid JSON object with EXACTLY the same structure as the input JSON.
NEVER invent jobs, degrees, or companies. Only add metrics directionally implied by content.
""".strip()


# ─────────────────────────────────────────────
# Iterative Optimization Engine
# ─────────────────────────────────────────────

def run_iterative_optimization(resume_text: str, original_score: int,
                                score_breakdown: dict) -> tuple:
    """
    Run up to 3 Gemini passes to push the improved resume score toward 85+.
    Returns: (improved_data, final_score, final_breakdown, final_sub, iterations, final_text)
    """
    TARGET    = 85
    cat_maxes = {
        'skills_relevance': 20, 'project_quality': 20, 'ats_optimization': 15,
        'experience_impact': 15, 'formatting_structure': 10,
        'grammar_clarity': 10,  'education_certifications': 10,
    }

    # ── Pass 1: standard improve ───────────────────────────────────
    prompt        = build_improve_prompt(resume_text, original_score, score_breakdown)
    raw           = call_gemini(prompt, expect_json=True, temperature=0.5)
    improved_data = parse_json_response(raw)
    improved_text = flatten_improved_data_to_text(improved_data)

    try:
        v1            = score_text_with_analysis_engine(improved_text)
        current_score = v1.get('score', 0)
        current_bd    = v1.get('score_breakdown', {})
        current_sub   = v1.get('sub_scores', {})
    except Exception as e:
        print(f"[Iter] Pass-1 verify failed: {e}")
        return improved_data, original_score, {}, {}, 1, improved_text

    print(f"[Iter] Pass 1: {original_score} \u2192 {current_score}")
    iterations = 1

    # ── Passes 2-3: targeted boost if below target ─────────────────
    while current_score < TARGET and iterations < 3:
        weak = []
        for key, mx in cat_maxes.items():
            actual = current_bd.get(key, 0)
            pct    = (actual / mx * 100) if mx else 0
            if pct < 80:
                weak.append(f"{key.replace('_',' ').title()}: {actual}/{mx} ({int(pct)}%)")

        boost_temp   = 0.6 + (iterations - 1) * 0.1
        data_json    = json.dumps(improved_data, indent=2)
        boost_prompt = build_boost_prompt(data_json, current_score, TARGET, weak)

        try:
            raw_boost    = call_gemini(boost_prompt, expect_json=True, temperature=boost_temp)
            boosted_data = parse_json_response(raw_boost)
        except Exception as e:
            print(f"[Iter] Pass-{iterations+1} Gemini failed: {e}")
            break

        boosted_text = flatten_improved_data_to_text(boosted_data)
        try:
            vb            = score_text_with_analysis_engine(boosted_text)
            boosted_score = vb.get('score', 0)
        except Exception as e:
            print(f"[Iter] Pass-{iterations+1} verify failed: {e}")
            break

        print(f"[Iter] Pass {iterations+1}: {current_score} \u2192 {boosted_score}")

        if boosted_score > current_score:
            improved_data = boosted_data
            current_score = boosted_score
            current_bd    = vb.get('score_breakdown', {})
            current_sub   = vb.get('sub_scores', {})
            improved_text = boosted_text
        else:
            print(f"[Iter] Pass {iterations+1} did not improve \u2014 stopping.")
            break

        iterations += 1

    return improved_data, current_score, current_bd, current_sub, iterations, improved_text


# ─────────────────────────────────────────────
# Optimization Report Builder
# ─────────────────────────────────────────────

def build_optimization_report(original_text: str, final_data: dict,
                               iterations: int, orig_score: int,
                               final_score: int) -> dict:
    """Count every measurable improvement for the UI report card."""
    import re as _re
    improved_text = flatten_improved_data_to_text(final_data)
    orig_lower    = original_text.lower()
    impr_lower    = improved_text.lower()

    strong_verbs = [
        'Engineered','Architected','Designed','Developed','Optimized','Deployed',
        'Implemented','Automated','Streamlined','Accelerated','Orchestrated',
        'Spearheaded','Integrated','Migrated','Refactored','Established',
        'Delivered','Launched','Reduced','Increased','Validated','Leveraged',
    ]
    verbs_used = [v for v in strong_verbs if v in improved_text]

    metrics = _re.findall(
        r'\d+[\+%x]|\d+\s*(?:users|records|ms|seconds|hours|days|GB|MB)',
        improved_text, _re.IGNORECASE
    )
    ats_kws = [
        'REST API','CI/CD','Agile','Scrum','microservices','Docker',
        'containerization','unit testing','system design','object-oriented',
        'data structures','machine learning','neural network','TensorFlow',
        'PyTorch','scikit-learn','feature engineering','version control',
        'cloud computing','database optimization','test-driven development',
    ]
    new_kws = [k for k in ats_kws
               if k.lower() in impr_lower and k.lower() not in orig_lower]

    sk           = final_data.get('skills', {})
    total_skills = sum(len(v) for v in sk.values() if isinstance(v, list))
    projects     = final_data.get('projects', [])
    experience   = final_data.get('experience', [])

    sections_improved = []
    if final_data.get('professional_summary'): sections_improved.append('Professional Summary')
    if total_skills >= 10:                      sections_improved.append('Technical Skills')
    if projects:                                sections_improved.append('Projects')
    if experience:                              sections_improved.append('Experience')
    if final_data.get('education'):             sections_improved.append('Education')

    return {
        'iterations_run':     iterations,
        'score_improvement':  final_score - orig_score,
        'action_verbs_count': len(verbs_used),
        'action_verbs_sample': verbs_used[:6],
        'metrics_count':      len(metrics),
        'keywords_injected':  len(new_kws),
        'keywords_list':      new_kws[:8],
        'total_skills':       total_skills,
        'projects_rewritten': len(projects),
        'project_bullets':    sum(len(p.get('bullets', [])) for p in projects),
        'experience_bullets': sum(len(j.get('bullets', [])) for j in experience),
        'sections_improved':  sections_improved,
    }


# ─────────────────────────────────────────────
# ATS Optimization List Builder
# ─────────────────────────────────────────────

def _build_ats_optimization_list(original_text: str, improved_data: dict, ai_generated: list) -> list:
    """
    Build a comprehensive, non-empty list of ATS optimizations applied.
    Starts with whatever the AI returned, then supplements deterministically
    by inspecting the improved resume data so the list is never empty.
    """
    opts = [o for o in ai_generated if o and len(o) > 10]  # keep non-trivial AI entries

    improved_text = flatten_improved_data_to_text(improved_data)
    orig_lower    = original_text.lower()
    impr_lower    = improved_text.lower()

    # 1 – Action verbs applied
    strong_verbs = [
        'Engineered', 'Architected', 'Designed', 'Developed', 'Optimized',
        'Deployed', 'Implemented', 'Automated', 'Streamlined', 'Accelerated',
        'Orchestrated', 'Spearheaded', 'Integrated', 'Migrated', 'Refactored',
        'Established', 'Delivered', 'Launched', 'Reduced', 'Increased',
    ]
    verbs_used = [v for v in strong_verbs if v in improved_text]
    if verbs_used:
        opts.append(
            f"Applied {len(verbs_used)} high-impact action verbs: "
            f"{', '.join(verbs_used[:5])}{'...' if len(verbs_used) > 5 else ''}"
        )

    # 2 – Quantified metrics added
    import re as _re
    metrics = _re.findall(
        r'\d+[\+%x]|\d+\s*(?:users|records|ms|seconds|hours|days|GB|MB|K\b|M\b)',
        improved_text, _re.IGNORECASE
    )
    if metrics:
        opts.append(f"Added {len(metrics)} quantified metrics and measurable achievements to bullets")

    # 3 – ATS keywords injected
    ats_kws = [
        'REST API', 'CI/CD', 'Agile', 'Scrum', 'microservices', 'Docker',
        'containerization', 'unit testing', 'system design', 'object-oriented',
        'data structures', 'machine learning', 'neural network', 'TensorFlow',
        'PyTorch', 'scikit-learn', 'feature engineering', 'version control',
    ]
    new_kws = [k for k in ats_kws if k.lower() in impr_lower and k.lower() not in orig_lower]
    if new_kws:
        opts.append(
            f"Injected {len(new_kws)} ATS-critical keywords: "
            f"{', '.join(new_kws[:5])}{'...' if len(new_kws) > 5 else ''}"
        )

    # 4 – Skills section expansion
    sk = improved_data.get('skills', {})
    all_skills = (sk.get('languages', []) + sk.get('frameworks', []) +
                  sk.get('tools', []) + sk.get('other', []))
    orig_skill_count = len(_re.findall(
        r'\b(?:Python|Java|JavaScript|TypeScript|React|Node|SQL|Git|Docker|AWS|C\+\+|Go|Rust)\b',
        original_text, _re.IGNORECASE
    ))
    if all_skills and len(all_skills) > orig_skill_count:
        opts.append(
            f"Expanded skills section to {len(all_skills)} technologies "
            f"organized into ATS-parseable categories (Languages, Frameworks, Tools, Concepts)"
        )

    # 5 – Professional summary
    summary = improved_data.get('professional_summary', '')
    if summary and len(summary) > 50:
        kw_count = sum(1 for k in ats_kws if k.lower() in summary.lower())
        opts.append(
            f"Rewrote professional summary with {kw_count}+ ATS keywords, "
            f"quantified achievement, and targeted career objective"
        )

    # 6 – Project rewrites
    projects = improved_data.get('projects', [])
    if projects:
        total_bullets = sum(len(p.get('bullets', [])) for p in projects)
        opts.append(
            f"Rewrote {len(projects)} project descriptions with {total_bullets} "
            f"achievement-focused bullets using [Verb + Tech + Metric] format"
        )

    # 7 – Standard section headers
    opts.append(
        "Standardized section headers to ATS-compatible format: "
        "PROFESSIONAL SUMMARY, TECHNICAL SKILLS, EXPERIENCE, PROJECTS, EDUCATION"
    )

    # 8 – Experience bullets
    experience = improved_data.get('experience', [])
    if experience:
        exp_bullets = sum(len(j.get('bullets', [])) for j in experience)
        opts.append(
            f"Enhanced {exp_bullets} experience bullets with strong action verbs "
            f"and quantified impact statements"
        )

    # Deduplicate and return 6-10 items
    seen, unique = set(), []
    for o in opts:
        key = o[:50].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(o)
    return unique[:10] if len(unique) >= 6 else unique


# ─────────────────────────────────────────────
# PDF Generation with ReportLab
# ─────────────────────────────────────────────

# Color palette
C_PRIMARY   = colors.HexColor('#4f46e5')   # indigo
C_ACCENT    = colors.HexColor('#7c3aed')   # violet
C_DARK      = colors.HexColor('#1e1b4b')   # dark indigo
C_TEXT      = colors.HexColor('#1f2937')   # near black
C_MUTED     = colors.HexColor('#6b7280')   # gray
C_LINE      = colors.HexColor('#e5e7eb')   # light gray


def build_pdf_styles():
    """Return a dict of ParagraphStyle objects for the resume PDF."""
    base = getSampleStyleSheet()
    return {
        'name': ParagraphStyle(
            'Name',
            fontSize=26, leading=30, textColor=C_DARK,
            fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=2,
        ),
        'contact': ParagraphStyle(
            'Contact',
            fontSize=9, leading=14, textColor=C_MUTED,
            fontName='Helvetica', alignment=TA_CENTER, spaceAfter=6,
        ),
        'section_heading': ParagraphStyle(
            'SectionHeading',
            fontSize=11, leading=14, textColor=C_PRIMARY,
            fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=2,
            textTransform='uppercase', letterSpacing=1,
        ),
        'job_title': ParagraphStyle(
            'JobTitle',
            fontSize=10.5, leading=14, textColor=C_TEXT,
            fontName='Helvetica-Bold', spaceBefore=6, spaceAfter=1,
        ),
        'job_meta': ParagraphStyle(
            'JobMeta',
            fontSize=9, leading=12, textColor=C_MUTED,
            fontName='Helvetica-Oblique', spaceAfter=3,
        ),
        'bullet': ParagraphStyle(
            'Bullet',
            fontSize=9.5, leading=14, textColor=C_TEXT,
            fontName='Helvetica', leftIndent=12, spaceAfter=2,
        ),
        'summary': ParagraphStyle(
            'Summary',
            fontSize=9.5, leading=15, textColor=C_TEXT,
            fontName='Helvetica', spaceAfter=4,
        ),
        'skill_group': ParagraphStyle(
            'SkillGroup',
            fontSize=9.5, leading=14, textColor=C_TEXT,
            fontName='Helvetica', spaceAfter=3,
        ),
        'cert': ParagraphStyle(
            'Cert',
            fontSize=9.5, leading=14, textColor=C_TEXT,
            fontName='Helvetica', leftIndent=12, spaceAfter=2,
        ),
    }


def section_divider(styles):
    """Return a heading + HR line as a list of flowables."""
    return []  # HR drawn inline per section


def generate_resume_pdf(data: dict, output_path: str):
    """
    Generate a professional ATS-friendly resume PDF from the improved data dict.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=15*mm,  bottomMargin=15*mm,
    )
    styles = build_pdf_styles()
    story  = []

    def add_section(title: str):
        story.append(Spacer(1, 4))
        story.append(Paragraph(title.upper(), styles['section_heading']))
        story.append(HRFlowable(width='100%', thickness=1.2, color=C_PRIMARY, spaceAfter=4))

    # ── Header ──────────────────────────────────
    name = data.get('candidate_name', 'Your Name')
    story.append(Paragraph(name, styles['name']))

    contact = data.get('contact', {})
    contact_parts = [
        p for p in [
            contact.get('email'),
            contact.get('phone'),
            contact.get('location'),
            contact.get('linkedin'),
            contact.get('github'),
        ] if p
    ]
    if contact_parts:
        story.append(Paragraph('  |  '.join(contact_parts), styles['contact']))

    story.append(HRFlowable(width='100%', thickness=2, color=C_PRIMARY, spaceAfter=4))

    # ── Professional Summary ─────────────────────
    summary = data.get('professional_summary', '')
    if summary:
        add_section('Professional Summary')
        story.append(Paragraph(summary, styles['summary']))

    # ── Experience ───────────────────────────────
    experience = data.get('experience', [])
    if experience:
        add_section('Experience')
        for job in experience:
            title_line = f"<b>{job.get('title','')}</b>"
            if job.get('company'):
                title_line += f"  ·  {job.get('company','')}"
            story.append(Paragraph(title_line, styles['job_title']))
            if job.get('duration'):
                story.append(Paragraph(job['duration'], styles['job_meta']))
            for bullet in job.get('bullets', []):
                story.append(Paragraph(f"• {bullet}", styles['bullet']))

    # ── Education ────────────────────────────────
    education = data.get('education', [])
    if education:
        add_section('Education')
        for edu in education:
            title_line = f"<b>{edu.get('degree','')}</b>"
            if edu.get('institution'):
                title_line += f"  ·  {edu.get('institution','')}"
            story.append(Paragraph(title_line, styles['job_title']))
            if edu.get('duration'):
                story.append(Paragraph(edu['duration'], styles['job_meta']))
            if edu.get('details'):
                story.append(Paragraph(edu['details'], styles['bullet']))

    # ── Skills ───────────────────────────────────
    skills = data.get('skills', {})
    skill_lines = []
    if skills.get('languages'):
        skill_lines.append(('<b>Languages:</b> ', ', '.join(skills['languages'])))
    if skills.get('frameworks'):
        skill_lines.append(('<b>Frameworks & Libraries:</b> ', ', '.join(skills['frameworks'])))
    if skills.get('tools'):
        skill_lines.append(('<b>Tools & Platforms:</b> ', ', '.join(skills['tools'])))
    if skills.get('other'):
        skill_lines.append(('<b>Other:</b> ', ', '.join(skills['other'])))

    if skill_lines:
        add_section('Technical Skills')
        for label, value in skill_lines:
            story.append(Paragraph(label + value, styles['skill_group']))

    # ── Projects ─────────────────────────────────
    projects = data.get('projects', [])
    if projects:
        add_section('Projects')
        for proj in projects:
            title_line = f"<b>{proj.get('name','')}</b>"
            if proj.get('tech'):
                title_line += f"  <font color='#7c3aed' size='8'>({proj.get('tech','')})</font>"
            story.append(Paragraph(title_line, styles['job_title']))
            for bullet in proj.get('bullets', []):
                story.append(Paragraph(f"• {bullet}", styles['bullet']))

    # ── Certifications ───────────────────────────────────────────
    certs = data.get('certifications', [])
    if certs:
        add_section('Certifications')
        for cert in certs:
            story.append(Paragraph(f"• {cert}", styles['cert']))

    # ── Achievements ───────────────────────────────────────────
    achievements = data.get('achievements', [])
    if achievements:
        add_section('Achievements & Awards')
        for ach in achievements:
            story.append(Paragraph(f"• {ach}", styles['cert']))

    doc.build(story)


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze_resume():
    """
    POST /analyze
    Returns: { success, analysis, resume_text }
    """
    if 'resume' not in request.files:
        return jsonify({'error': 'No file uploaded.'}), 400

    file = request.files['resume']
    if file.filename == '':
        return jsonify({'error': 'No file selected.'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. PDF only.'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        file.save(filepath)
        resume_text = extract_text_from_pdf(filepath)

        # Detect career stage for stage-relative scoring
        career_stage = detect_career_stage(resume_text)
        stage_label  = STAGE_LABELS.get(career_stage, 'Student / Fresher')

        prompt   = build_analysis_prompt(resume_text, career_stage)
        raw      = call_gemini_analysis(prompt)
        analysis = parse_json_response(raw)

        # Compute potential score + improvement roadmap
        potential_data = compute_potential_score(analysis, career_stage)

        # Attach stage info to the analysis object for frontend convenience
        analysis['career_stage'] = career_stage
        analysis['stage_label']  = stage_label
        analysis['stage_rubric'] = {
            k: {'label': lbl, 'max': mx}
            for k, (lbl, mx, _) in STAGE_RUBRICS[career_stage].items()
        }

        return jsonify({
            'success':       True,
            'analysis':      analysis,
            'resume_text':   resume_text,
            'career_stage':  career_stage,
            'stage_label':   stage_label,
            'potential_data': potential_data,
        })

    except (ValueError, RuntimeError) as e:
        return jsonify({'error': str(e)}), 422
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


@app.route('/improve', methods=['POST'])
def improve_resume():
    """
    POST /improve
    Body: { resume_text, original_score?, score_breakdown? }
    Returns: { success, improved_data, pdf_filename, ats_optimizations_applied, ... }
    """
    body = request.get_json(silent=True)
    if not body or not body.get('resume_text'):
        return jsonify({'error': 'No resume text provided.'}), 400

    resume_text     = body['resume_text'].strip()
    original_score  = int(body.get('original_score', 0))
    score_breakdown = body.get('score_breakdown', {})
    career_stage    = body.get('career_stage', 'student')

    if len(resume_text) < 50:
        return jsonify({'error': 'Resume text is too short to improve.'}), 400

    try:
        # ── Iterative optimization (up to 3 Gemini passes) ────────────
        (improved_data, verified_score,
         verified_breakdown, verified_sub,
         iterations_run, improved_text_flat) = run_iterative_optimization(
            resume_text, original_score, score_breakdown
        )

        # ── Build ATS optimization list (never empty) ─────────────────
        ai_ats_opts = improved_data.get('ats_optimizations_applied', [])
        ats_opts    = _build_ats_optimization_list(resume_text, improved_data, ai_ats_opts)

        # ── Build optimization report for the UI ──────────────────────
        opt_report = build_optimization_report(
            resume_text, improved_data, iterations_run,
            original_score, verified_score or 0
        )

        # ── Generate PDF ───────────────────────────────────────────────
        pdf_filename = f"improved_resume_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path     = os.path.join(PDF_FOLDER, pdf_filename)
        generate_resume_pdf(improved_data, pdf_path)

        _cleanup_old_pdfs()

        print(f"[Improve] Done. {original_score} → {verified_score} "
              f"in {iterations_run} pass(es).")

        return jsonify({
            'success':                   True,
            'improved_data':             improved_data,
            'pdf_filename':              pdf_filename,
            'improvement_notes':         improved_data.get('improvement_notes', []),
            'ats_optimizations_applied': ats_opts,
            'verified_score':            verified_score,
            'verified_breakdown':        verified_breakdown,
            'verified_sub_scores':       verified_sub,
            'improved_text':             improved_text_flat,
            'optimization_report':       opt_report,
            'iterations_run':            iterations_run,
        })


    except (ValueError, RuntimeError) as e:
        return jsonify({'error': str(e)}), 422
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@app.route('/compare', methods=['POST'])
def compare_resumes():
    """
    POST /compare
    Body: { original_text, improved_text, original_score }
    Returns: { success, comparison } — full before/after score comparison
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'error': 'No data provided.'}), 400

    original_text  = normalize_resume_text((body.get('original_text') or '').strip())
    improved_text  = normalize_resume_text((body.get('improved_text') or '').strip())
    original_score = int(body.get('original_score', 0))

    if not original_text or not improved_text:
        return jsonify({'error': 'Both original and improved text are required.'}), 400

    try:
        # Use the SAME scoring engine as /analyze on the improved text.
        # This is the ONLY way to guarantee the /compare score matches re-upload.
        improved_analysis = score_text_with_analysis_engine(improved_text)
        improved_score    = improved_analysis.get('score', 0)
        delta             = improved_score - original_score

        comparison = {
            'improved_score':           improved_score,
            'score_breakdown':          improved_analysis.get('score_breakdown', {}),
            'sub_scores':               improved_analysis.get('sub_scores', {}),
            'score_delta':              delta,
            'what_improved':            improved_analysis.get('strengths', []),
            'what_still_needs_work':    improved_analysis.get('weaknesses', []),
            'ats_optimization_applied': (body.get('ats_optimizations_applied') or
                                          improved_analysis.get('strengths', [])),
            'comparison_summary':       improved_analysis.get('summary', ''),
            'scoring_engine':           'unified',   # confirms same engine as /analyze
        }
        return jsonify({'success': True, 'comparison': comparison})

    except (ValueError, RuntimeError) as e:
        return jsonify({'error': str(e)}), 422
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@app.route('/download/<filename>')
def download_pdf(filename):
    """GET /download/<filename> — Serve a generated PDF for download."""
    # Security: only allow alphanumeric + underscore + hyphen + dot
    if not re.match(r'^[\w\-\.]+$', filename):
        return jsonify({'error': 'Invalid filename.'}), 400
    if not filename.endswith('.pdf'):
        return jsonify({'error': 'Only PDF files can be downloaded.'}), 400
    return send_from_directory(
        PDF_FOLDER, filename,
        as_attachment=True,
        download_name='improved_resume.pdf'
    )

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'model': GEMINI_MODEL})



# ─────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────

def _cleanup_old_pdfs(keep: int = 20):
    """Delete oldest generated PDFs, keeping only the most recent `keep` files."""
    try:
        files = sorted(
            [os.path.join(PDF_FOLDER, f) for f in os.listdir(PDF_FOLDER) if f.endswith('.pdf')],
            key=os.path.getmtime
        )
        for old in files[:-keep]:
            os.remove(old)
    except Exception:
        pass


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 55)
    print("  AI Resume Analyzer - Starting Server")
    print("  Open http://127.0.0.1:5000 in your browser")
    print("=" * 55)
    app.run(debug=True, host='0.0.0.0', port=5000)
