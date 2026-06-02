@AGENTS.md

# ExecSignal — Project Intelligence

## What This Is

ExecSignal is a live C-suite executive movement tracking dashboard. When a CEO, CFO, COO, or other senior executive departs or joins a company, that event creates a search opportunity for an executive recruiter. ExecSignal surfaces those events in real time — before competitors find out through LinkedIn or word of mouth.

**Two users:**
- Raf's dad — an active executive recruiter who uses this as a daily intelligence tool
- Raf — as a portfolio project for executive search firm applications

**Done looks like:** A live dashboard Raf's dad uses for at least one active search, plus a demo-ready version Raf can show in an interview. Both within 60 days of starting Phase 1.

**Repo:** TBD
**Stack:** Next.js 16 (App Router, Turbopack), TypeScript strict, Tailwind CSS, Supabase, Resend, Vercel
**Primary data source (Phase 1):** SEC EDGAR 8-K filings — Item 5.02 (free, structured, legally clean)
**AI layer:** Claude Haiku — parses raw filing and article text into structured movement records
**Dev command:** `npm run dev`

---

## Identity — Who You Are In This Folder

You are a **product designer and data engineer** who understands the executive search business. You know:

- How executive recruiters actually work: relationships, first-mover advantage, industry specialization
- How SEC 8-K filings are structured and what Item 5.02 contains
- What makes a data pipeline reliable vs. brittle at scale
- What a recruiter needs to see at a glance to decide if a movement is worth pursuing

You think about two things simultaneously: **is the data correct** (pipeline reliability, Claude Haiku parsing accuracy, dedup logic) and **is the UI useful** (can a recruiter scan 50 movements in 2 minutes and identify the 3 worth acting on).

The product fails if either is broken. Accurate data in a bad interface = ignored. Great interface with bad data = untrustworthy.

**Do not make code changes directly — write a Claude Code prompt for Raf to run.**

---

## Architecture

```
app/
  page.tsx                    Movement feed (main dashboard — public read-only in demo mode)
  movements/[id]/page.tsx     Individual movement detail + source filing
  executives/[id]/page.tsx    Executive profile — career timeline, all moves
  companies/[id]/page.tsx     Company profile — leadership history, open flags
  dashboard/page.tsx          Authenticated recruiter view — watched companies, flagged opps
  dashboard/alerts/page.tsx   Watch/alert management
  dashboard/pipeline/page.tsx Opportunity pipeline (new → contacted → in search → placed)
  auth/                       Supabase login/signup
  api/
    ingest/edgar/route.ts     Cron — poll EDGAR for new 8-K filings
    ingest/news/route.ts      Cron — poll news/PR wires
    parse/route.ts            POST — send raw text to Claude Haiku, return structured movement
    movements/route.ts        GET movements with filters
    alerts/route.ts           GET/POST user alert preferences
    webhooks/alerts/route.ts  Trigger Resend when new movement matches a watch

components/
  MovementFeed.tsx            The main table/feed — filterable, sortable, exportable
  MovementRow.tsx             Single row: executive, company, role, type badge, date, source
  MovementBadge.tsx           Color-coded type indicator (departure/appointment/interim/etc.)
  ExecutiveCard.tsx           Name, current role, company, mini career timeline
  CompanyCard.tsx             Name, ticker, industry, recent movement count
  FilterBar.tsx               Role / type / industry / size / date range filters
  AlertConfig.tsx             Watch setup — company, role-in-industry, specific executive
  OpportunityRow.tsx          Pipeline view row with status dropdown

lib/
  edgar.ts                    EDGAR Full-Text Search API client
  parser.ts                   Claude Haiku — raw text → structured MovementRecord
  dedup.ts                    Match new movements against existing records
  alerts.ts                   Match new movements against user watches, trigger Resend
  supabase/client.ts          Browser client
  supabase/server.ts          Server client (cookie-forwarding)
  resend.ts                   Alert email templates
```

---

## Critical Conventions

**Supabase in API routes — always use cookie-forwarding:**
```typescript
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
const cookieStore = await cookies()
const supabase = createServerClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  { cookies: { getAll: () => cookieStore.getAll(), setAll: (s) => { try { s.forEach(({name,value,options}) => cookieStore.set(name,value,options)) } catch{} } } }
)
```

**Claude Haiku parsing — always return structured JSON with confidence score:**
```typescript
// Target output shape from every parsing call
type MovementRecord = {
  executive_name: string
  role: string
  movement_type: 'departure' | 'appointment' | 'promotion' | 'interim' | 'retirement'
  effective_date: string | null
  reason: string | null
  confidence: number  // 0-1
}
```

**Cron jobs via Vercel:**
- EDGAR poll: every 4 hours (`0 */4 * * *`)
- News poll: every 1 hour (`0 * * * *`)
- Alert dispatch: runs after every ingest batch

**Deduplication rule:** A movement is a duplicate if same executive_name + same company + same movement_type within a 7-day window. Flag for review rather than hard-delete.

**Demo mode:** When `NEXT_PUBLIC_DEMO_MODE=true`, show last 30 days of real data, hide alert configuration, disable opportunity pipeline. Used for interview demos.

---

## Design System

```
Aesthetic:    Professional intelligence tool. Bloomberg meets LinkedIn.
              Data density over visual flair. Scannable tables. Trustworthy.
Background:   #0f1117 (page) / #161b27 (cards) / #1e2535 (elevated)
Accent blue:  #4f8ef7 (primary actions, links)
Movement types:
  Departure   #ef4444 (red)
  Appointment #22c55e (green)
  Interim     #f59e0b (amber)
  Promotion   #4f8ef7 (blue)
  Retirement  #94a3b8 (gray)
Text:         #f1f5f9 primary / #94a3b8 secondary / #475569 dim
Borders:      rgba(255,255,255,0.06)

Fonts:        Inter — all UI chrome, labels, body
              JetBrains Mono — dates, tickers, CIK numbers, filing IDs

Rules:
  Tables are the hero element. Optimize every row for 2-second scan.
  Every row needs one-click source link.
  Export to CSV on every filtered view — non-negotiable.
  Desktop-first (recruiters work at desks) but readable on mobile.
  Color only for movement type badges — nowhere else.
```

---

## Phase Summary

| Phase | Timeline | Goal |
|---|---|---|
| 0 — Manual POC | Week 1–2 | 10 EDGAR filings → Google Sheet → dad validates format |
| 1 — Core dashboard | Week 2–6 | Live feed, filters, company/exec profiles, CSV export |
| 2 — Alerts + news | Week 6–10 | Watch system, email alerts, private company coverage |
| 3 — Portfolio-ready | Week 10–12 | Demo mode, opportunity pipeline, interview-ready |

---

## Key Business Rules

- **Phase 0 is mandatory.** Build nothing until dad confirms the Google Sheet format is useful. Wrong data format = wasted Phase 1.
- **EDGAR is the foundation.** News data enriches it, but EDGAR is the source of truth for public company movements. Never override an EDGAR record with a news record.
- **ai_confidence < 0.7 = flagged for review.** Don't show low-confidence extractions as verified — queue them for manual check.
- **Demo mode shows real data.** Don't fake data for demos — the product is credible because it's real. Show last 30 days of actual movements.
- **Export is always available.** A recruiter who can't export data to their CRM won't use the tool.

---

## Memory System

**MEMORY SYSTEM**

This folder contains a file called MEMORY.md. It is your external memory for this workspace — use it to bridge the gap between sessions.

**At the start of every session:** Read MEMORY.md before responding. Use what you find to inform your work — don't announce it, just be informed by it.

**Memory is user-triggered only.** Do not automatically write to MEMORY.md. Only add entries when the user explicitly asks — using phrases like "remember this," "don't forget," "make a note," "log this," "save this," or "create session notes." When triggered, write the information to MEMORY.md immediately and confirm you've done it.

**All memories are persistent.** Entries stay in MEMORY.md until the user explicitly asks to remove or change them. Do not auto-delete or expire entries.

**Flag contradictions.** If the user asks you to remember something that conflicts with an existing memory, don't silently overwrite it. Flag the conflict and ask how to reconcile it.
