# ExecSignal — Product Spec v1.0
_Created: 2026-06-02_

---

## What This Is

ExecSignal is a live intelligence dashboard that tracks C-suite executive movements — departures, appointments, lateral moves, and promotions across industries. When a CEO leaves a company, that company immediately needs to hire a new one. A recruiter who knows about it in the first 24 hours has a head start on every competitor.

**Two users, two use cases:**
1. **Raf's dad (active recruiter):** A daily-use tool to surface search opportunities before other recruiters see them. Filter by industry, role, company size. Export to CRM. Set alerts on watched companies.
2. **Raf (portfolio piece):** A live, functional product he can demo when applying to executive search firms — proves he understands the business, can build tools, and thinks like a recruiter.

**The insight behind it:** Executive recruiters rely on relationships, reputation, and being first. Being first is the only one that can be systematized. ExecSignal systematizes first-mover awareness.

---

## Done Looks Like

A live dashboard Raf's dad uses for at least one active search, plus a version Raf can demo in an interview — both within 60 days of starting Phase 1.

---

## What Raf Is Willing To Do That Isn't Fun

Writing SEC EDGAR parsers, normalizing messy executive name and company data, dealing with inconsistent filing formats, and manually verifying edge cases when Claude misclassifies a movement type.

---

## The Business Case

When a C-suite executive departs a public company, the company files an 8-K with the SEC within 4 business days. That filing is public, free, and structured. Every executive recruiter in the world could be reading these the moment they're filed. Almost none of them do — they find out via LinkedIn, word of mouth, or the client calling them.

That lag is the product.

**What triggers a search opportunity:**
- CEO / CFO / COO / CTO / CMO departs → company needs a replacement
- Executive joins a new company → their old role may be open, and they may need to build a new team
- Board member named interim CEO → search is likely already underway
- Private equity-backed company announces leadership change → PE firms move fast

---

## Hero Feature — Executive Movement Feed (fully specced)

### What it looks like

A real-time, filterable feed of executive movements. Each entry:

```
Jane Doe          CFO → Departed         Acme Corp (NASDAQ: ACME)
                  Filed: June 1, 2026    Industry: SaaS / Enterprise Software
                  Source: SEC 8-K        Company size: 1,200 employees
                  [View filing]  [Track company]  [Flag as opportunity]
```

### Filters

- **Role:** CEO / CFO / COO / CTO / CMO / CLO / CHRO / Board / All
- **Movement type:** Departure / Appointment / Promotion / Interim / Retirement
- **Industry:** Tech / Finance / Healthcare / Manufacturing / Energy / Consumer / All
- **Company size:** <500 / 500–5K / 5K–50K / 50K+ / All
- **Date range:** Last 24hrs / Last 7 days / Last 30 days / Custom
- **Source:** SEC only / News only / All

### Alert system

Recruiter sets up a watch on:
- Specific companies ("alert me when anyone at Goldman Sachs moves")
- Role types in an industry ("alert me on all CFO departures in healthcare")
- Specific executives ("alert me if Jane Doe moves")

Alert delivery: email digest (daily or instant). Powered by Resend.

### Executive profile page

Click any executive → a page showing:
- Current and previous roles (timeline)
- Companies they've worked at
- Average tenure per role
- Known board memberships
- Source links for each data point

### Company tracker

Click any company → a page showing:
- All C-suite movements in the last 2 years
- Current leadership team
- Flag button: "I'm watching this company"
- Open searches flagged by the recruiter

---

## Data Pipeline — Three Phases

### Phase 1 (MVP): SEC EDGAR only

**Why start here:** Free, structured, legally unambiguous, covers all ~4,900 US public companies, mandated 4-business-day filing window.

**How it works:**
- SEC EDGAR Full-Text Search API (`efts.sec.gov/LATEST/search-index?q=...`)
- Filter for 8-K filings, Item 5.02: "Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers"
- Cron job: polls EDGAR every 4 hours for new 8-K filings
- Claude Haiku: parses the filing text to extract: executive name, role, movement type (departure/appointment), effective date, reason if stated
- Structured output stored in Supabase

**Limitation:** Public companies only. Covers the Fortune 500 and beyond but misses private companies, PE-backed firms, and startups.

**Sample EDGAR query:**
```
GET https://efts.sec.gov/LATEST/search-index?q=%225.02%22&dateRange=custom&startdt=2026-06-01&enddt=2026-06-02&forms=8-K
```

### Phase 2: News and press releases

Add a second data source covering private companies, PE-backed firms, and international moves.

**Sources:**
- NewsAPI or GNews API — filter for keywords: "appoints", "names", "departs", "resigns", "joins as CEO/CFO/COO/CTO"
- PR Newswire RSS feed (free public feed)
- Business Wire RSS (free public feed)
- GlobeNewswire (free RSS)

**Pipeline:**
- Hourly fetch of relevant news items
- Claude Haiku: classify as executive movement or not, extract structured fields
- Dedup against EDGAR data (same person, same event)

### Phase 3: LinkedIn enrichment (manual or API)

Add headshots, full career history, connection depth. Either:
- LinkedIn API (heavily rate-limited, requires partnership)
- Manual enrichment for flagged executives
- Third-party enrichment (Clearbit, Apollo.io, Hunter) for email + LinkedIn URL

---

## Tech Stack

```
Frontend:     Next.js 16 (App Router), TypeScript strict, Tailwind CSS
Database:     Supabase (PostgreSQL) — executives, movements, companies, alerts, users
Auth:         Supabase Auth — email/password (Raf + dad, small user base initially)
Payments:     None in Phase 1 — internal tool only
Email:        Resend — alert digests, daily briefings
Data fetch:   Vercel cron jobs — EDGAR every 4hrs, news every 1hr
AI parsing:   Claude Haiku — extract structured data from filings and articles
Deployment:   Vercel
```

---

## Database Schema

```sql
executives (
  id uuid PRIMARY KEY,
  name text,
  linkedin_url text,
  headshot_url text,
  current_company_id uuid REFERENCES companies(id),
  current_role text,
  created_at timestamptz,
  updated_at timestamptz
)

companies (
  id uuid PRIMARY KEY,
  name text,
  ticker text,                   -- null for private
  exchange text,                 -- NYSE / NASDAQ / null
  industry text,
  sub_industry text,
  employee_count_range text,     -- '<500' | '500-5K' | '5K-50K' | '50K+'
  headquarters text,
  is_public boolean,
  cik text                       -- SEC Central Index Key for EDGAR lookup
)

movements (
  id uuid PRIMARY KEY,
  executive_id uuid REFERENCES executives(id),
  company_id uuid REFERENCES companies(id),
  role text,                     -- 'CEO' | 'CFO' | 'COO' | 'CTO' | 'CMO' | 'Board' etc.
  movement_type text,            -- 'departure' | 'appointment' | 'promotion' | 'interim' | 'retirement'
  effective_date date,
  announced_date date,
  reason text,                   -- 'personal reasons' | 'retirement' | 'new opportunity' | null
  source_type text,              -- 'sec_8k' | 'news' | 'press_release' | 'manual'
  source_url text,
  raw_text text,                 -- original filing or article text
  ai_confidence numeric,         -- 0-1, how confident Haiku was in extraction
  verified boolean,              -- manually confirmed
  created_at timestamptz
)

watches (
  id uuid PRIMARY KEY,
  user_id uuid REFERENCES auth.users(id),
  watch_type text,               -- 'company' | 'executive' | 'role_in_industry'
  company_id uuid REFERENCES companies(id),
  executive_id uuid REFERENCES executives(id),
  role_filter text,
  industry_filter text,
  alert_frequency text,          -- 'instant' | 'daily'
  created_at timestamptz
)

opportunities (
  id uuid PRIMARY KEY,
  movement_id uuid REFERENCES movements(id),
  user_id uuid REFERENCES auth.users(id),
  status text,                   -- 'new' | 'contacted' | 'in_search' | 'placed' | 'dead'
  notes text,
  created_at timestamptz
)
```

---

## Design System

```
Aesthetic:    Professional intelligence tool. Bloomberg meets LinkedIn.
              Dense data that's easy to scan. Not a startup dashboard.
Background:   #0f1117 (page) / #161b27 (cards) / #1e2535 (elevated)
Accent:       #4f8ef7 (primary blue — professional, trustworthy)
              #22c55e (green — new appointments)
              #ef4444 (red — departures)
              #f59e0b (amber — interim / flagged)
Text:         #f1f5f9 primary / #94a3b8 secondary / #475569 dim
Borders:      rgba(255,255,255,0.06) default

Fonts:        Inter (all UI — clean, data-dense, professional)
              JetBrains Mono (dates, tickers, filing numbers)

Movement type colors:
  Departure   → red badge
  Appointment → green badge
  Interim     → amber badge
  Promotion   → blue badge
  Retirement  → gray badge

Rules:
  Tables are the hero — optimize for scannability, not visual flair.
  Every row needs one-click access to the source document.
  Export to CSV on every filtered view.
  Mobile-readable but desktop-first (recruiters work at desks).
```

---

## Phase Roadmap

### Phase 0 — Manual proof of concept (Week 1–2)

Before writing one line of code: manually pull 10 recent 8-K filings from EDGAR, format them into a Google Sheet, share with Raf's dad. Does he actually use it? Does he find it valuable? Does the data format make sense for how he works?

**If yes:** build Phase 1. If the format is wrong, fix it in the sheet before building.

### Phase 1 — Core dashboard (Week 2–6)

- EDGAR 8-K pipeline (cron + Claude Haiku parser)
- Movement feed with filters
- Company and executive profile pages
- Manual opportunity flagging
- Basic auth (Raf + dad only)
- CSV export

**Success criteria:** Raf's dad logs in at least 3 days per week without being asked.

### Phase 2 — Alerts + news pipeline (Week 6–10)

- Watch/alert system with email delivery
- News/PR wire data source
- Private company coverage begins
- Daily briefing email (top 10 movements from watched industries)

**Success criteria:** Dad uses at least one alert lead for an active search.

### Phase 3 — Portfolio-ready + demo mode (Week 10–12)

- Public demo mode (read-only, sample data for interviews)
- Executive profile enrichment (LinkedIn URLs, headshots)
- Opportunity pipeline (track status from "new lead" to "placed")
- Polish: loading states, empty states, onboarding flow

**Success criteria:** Raf demos this in an executive search interview and gets asked how it works.

---

## Why This Works As A Portfolio Piece

Executive search firms (Korn Ferry, Spencer Stuart, Heidrick & Struggles, Russell Reynolds, Egon Zehnder) are traditionally relationship-driven and tech-light. Showing up with a live tool that:

1. Demonstrates you understand how searches originate
2. Shows you can systematize what recruiters currently do manually
3. Works in the actual recruiter workflow (not just a Figma mockup)

...positions you as someone who can modernize the practice, not just do the work.

The fact that your father actively uses it to run real searches makes it real — not a toy project. That's the line between a portfolio piece and a portfolio piece that gets you hired.
