# ENTERPRISE DIGITAL MARKETING AGENCY — GAP ANALYSIS & ROADMAP TO PRODUCTION-GRADE

**Date:** 2026-08-25  
**Auditor:** Enterprise Full-Stack Developer / Product Architect  
**Repo:** `tanviruchahs2580/Autonomous-AI-Video-Agency` @ `f292950`  
**Perspective:** "Enterprise digital marketing agency SOP" — not generic API product

---

## 1. PRODUCT GOAL RE-READ (What the user actually wants)

The user is building an **enterprise-grade digital marketing agency platform** that:
1. Takes client briefs → produces professional marketing videos autonomously
2. Serves **multiple clients** (agencies manage many brands)
3. Has a **client-facing portal** for brief submission, review, feedback, approval
4. Has an **internal team dashboard** for producers/editors/reviewers
5. Follows **agency SOP**: campaign management, creative revision cycles, brand compliance, client communication, delivery, reporting, billing
6. Is **international-grade** in UX/visual quality
7. Supports **Bangla + English** content

**Current state:** The backend engine is excellent (84/100 engineering). But as a *digital marketing agency platform*, it is currently at the **"engine without a car"** stage — powerful API + worker pipeline, but zero client-facing surface, no creative revision workflow, no brand kit system.

---

## 2. CURRENT STATE — What Stage Is The Product At?

| Layer | Status | Completeness |
|---|---|---|
| Core pipeline (20 stages) | ✅ Complete | 95% |
| API backend (32 routes) | ✅ Complete | 90% |
| Multi-tenancy + RBAC | ✅ Complete | 85% |
| Worker reliability | ✅ Complete | 90% |
| Security | ✅ Complete | 90% |
| Observability | ✅ Good | 80% |
| CI/CD | ✅ Complete | 95% |
| Documentation | ✅ Excellent | 95% |
| **Frontend UI** | ❌ Missing | **0%** |
| **Client portal** | ❌ Missing | **0%** |
| **Creative revision workflow** | ❌ Missing | **0%** |
| **Brand kit management** | ❌ Missing | **0%** |
| **Campaign management** | ❌ Missing | **0%** |
| **Multi-language TTS** | ⚠️ Partial (edge-tts supports it, not exposed) | 30% |
| **Team collaboration** | ❌ Missing | 0% |
| **Client notifications** | ⚠️ Webhooks only | 40% |
| **Reporting/analytics** | ⚠️ Basic cost/events | 30% |
| **Billing/invoicing** | ❌ Missing | 0% |

**Product stage:** **RELEASE CANDIDATE for API-only B2B integration. NOT READY as a full agency platform.**

---

## 3. WHAT I FACED USING IT (Developer-as-User Test)

I tried to use the system as a digital marketing agency account manager would:

| # | What I Tried | Problem Faced |
|---|---|---|
| 1 | Submit a client brief via UI | **No UI exists.** Must craft JSON manually and POST to `/v1/projects`. A non-technical account manager cannot do this. |
| 2 | Review the generated video before sending to client | No preview player. Must download MP4 and open locally. No in-browser review. |
| 3 | Request a revision ("change the CTA text") | **No revision endpoint.** Must create an entirely new project+job from scratch. No way to edit script or swap a scene and re-render. |
| 4 | Add client's logo to the video | **No brand asset upload or overlay system.** Only procedural palette-based visuals. |
| 5 | Send the video to the client for approval | No client portal, no shareable link, no email notification. Must manually download and send. |
| 6 | Track multiple campaigns for one client | No campaign entity. Projects are flat; no grouping by client/campaign/quarter. |
| 7 | Generate video in Bangla | Brief accepts Bangla text but TTS provider defaults to English voice (`en-US-AriaNeural`). No `language` parameter passed to edge-tts. Captions will be English-styled. |
| 8 | See which jobs are running right now | Must call `/v1/jobs?state=running` via curl. No live dashboard with progress bars. |
| 9 | Know how much a client has spent this month | `/v1/costs` returns totals but no per-client monthly rollup or budget remaining. |
| 10 | Onboard a new team member | Can issue API keys, but there is no invitation flow, no password, no login page — pure API key model unsuitable for human users. |

---

## 4. COMPLETE GAP REGISTER

### Category A: Frontend / Client Portal (CRITICAL for agency SOP)

| # | Gap | Priority | Why It Matters |
|---|---|---|---|
| A-1 | **No web frontend at all** | P0 | Account managers and clients cannot use an API. Agency SOP requires a visual interface. |
| A-2 | **No client portal** (brief submission form, video preview player, approve/request-revision buttons) | P0 | Clients are the ones who approve deliverables. Without a portal, the "approval" workflow cannot happen in-product. |
| A-3 | **No internal dashboard** (job queue view, progress bars, stage indicators, failure alerts) | P0 | Producers need to see what's rendering, what failed, what needs review — at a glance. |
| A-4 | **No video preview player** with in-browser playback | P0 | Reviewing a video requires downloading and opening in VLC. This breaks the workflow. |
| A-5 | **No notification center** (in-app + email) | P1 | "Your video is ready for review" must reach the right person. |

### Category B: Creative Revision Workflow (CRITICAL for agency SOP)

| # | Gap | Priority | Why It Matters |
|---|---|---|---|
| B-1 | **No script revision endpoint** (`PATCH /v1/projects/{id}/script`) | P0 | Client says "change hook text" → producer must be able to edit script and re-render without recreating everything. |
| B-2 | **No scene-level editing** (swap image, change duration, reorder scenes) | P1 | Fine-grained control expected by any agency. |
| B-3 | **No revision history** (v1, v2, v3… with diff) | P1 | Clients ask "what changed?" — need audit trail of revisions. |
| B-4 | **No approval state machine per deliverable** (draft → internal review → client review → approved → rejected → revised) | P0 | Agency SOP requires formal approval cycles. Currently only a binary gate exists. |
| B-5 | **No comment/annotation system on videos** (timestamped feedback) | P2 | "At 0:15 the logo is too small" — standard agency feedback format. |

### Category C: Brand Kit Management (HIGH for agency SOP)

| # | Gap | Priority | Why It Matters |
|---|---|---|---|
| C-1 | **No brand kit entity** (logo files, font selection, color palette, intro/outro templates) | P1 | Every client has brand guidelines. Currently palette is passed per-brief; should persist per-client. |
| C-2 | **No logo/watermark overlay in renders** | P1 | Marketing videos always carry client branding. Current pipeline generates abstract scenes only. |
| C-3 | **No custom font loading** | P2 | Brand guidelines specify fonts; current system uses Arial fallback only. |
| C-4 | **No intro/outro template system** | P2 | Agencies reuse branded intro/outro across all videos for a client. |

### Category D: Campaign Management

| # | Gap | Priority | Why It Matters |
|---|---|---|---|
| D-1 | **No Campaign entity** (groups projects by client/objective/timeframe) | P1 | "Q3 Product Launch" contains 5 videos. Currently they're unrelated projects. |
| D-2 | **No Client entity separate from Tenant** (a tenant = agency; clients are sub-entities) | P1 | An agency manages many clients. Current `Tenant` = the agency itself. Need `clients` table under each tenant. |
| D-3 | **No campaign-level reporting** (all videos, total spend, status summary) | P2 | Account managers need campaign dashboards. |

### Category E: Localization / Internationalization

| # | Gap | Priority | Why It Matters |
|---|---|---|---|
| E-1 | **TTS language not configurable per project** | P1 | `brief.language` field exists but is never passed to edge-tts. Bangla/Hindi/Spanish briefs get English voices. |
| E-2 | **No Bangla-capable voice configured** | P1 | User explicitly wants international-grade including Bangla. `edge-tts` supports `bn-BD-NabanitaNeural` etc. — just needs wiring. |
| E-3 | **Caption styling not locale-aware** | P2 | Bangla script needs different font rendering than Latin. |
| E-4 | **UI localization framework missing** (when frontend is built) | P3 | i18n-ready from day 1 avoids refactoring. |

### Category F: Team Collaboration

| # | Gap | Priority | Why It Matters |
|---|---|---|---|
| F-1 | **No user authentication** (username/password/login flow) | P1 | API keys work for machines, not humans. Team members need login. |
| F-2 | **No role-based UI access** (producer sees queue, client sees only their deliverables) | P1 | RBAC exists at API level but no UI to experience it. |
| F-3 | **No assignment system** ("this job is assigned to Rafi") | P2 | Team coordination requires task ownership. |
| F-4 | **No activity feed** ("Rafi completed render, Sara approved") | P2 | Team awareness. |

### Category G: Reporting & Analytics

| # | Gap | Priority | Why It Matters |
|---|---|---|---|
| G-1 | **No agency dashboard** (total videos this month, revenue, active campaigns, pending approvals) | P1 | Management needs overview. |
| G-2 | **No per-client reporting** (videos delivered, average turnaround, spend) | P2 | Account management. |
| G-3 | **No export** (CSV/PDF report generation) | P3 | Client billing justification. |

### Category H: Billing & Invoicing

| # | Gap | Priority | Why It Matters |
|---|---|---|---|
| H-1 | **No pricing model** (per-video, subscription, retainer) | P2 | Agencies bill clients. |
| H-2 | **No invoice generation** | P3 | Downstream of pricing. |
| H-3 | **Cost tracking exists** but is internal-only, not client-billable | — | Already built, needs mapping to billing. |

---

## 5. WHAT MUST BE ADDED — Prioritized Roadmap

### Phase 1 — Minimum Viable Agency Platform (P0 — BLOCKING)

These are required before ANY client can use the system:

| Step | What to Build | Est. Effort | Dependencies |
|---|---|---|---|
| **1.1** | **Web Frontend** — Next.js 14+ (App Router), TailwindCSS, shadcn/ui components. Pages: Login, Dashboard, Projects List, Project Detail (with video player), New Brief Form, Deliverables Gallery, Settings. | 3–4 weeks | None |
| **1.2** | **Video Preview Player** — HTML5 `<video>` with signed URL from backend, timeline scrubber, fullscreen. Embedded in Project Detail. | 3 days | 1.1 |
| **1.3** | **Authentication** — JWT-based login/logout (email + password), refresh tokens, bcrypt hashing. Replaces raw API-key model for humans (API keys remain for machine-to-machine). | 1 week | None |
| **1.4** | **Script Revision Endpoint** — `PATCH /v1/projects/{id}/script` accepting updated sections; creates ScriptVersion v2; triggers re-render from `storyboard` stage onward. | 3 days | None |
| **1.5** | **Approval State Machine** — Per-deliverable: `draft → internal_review → client_review → approved | changes_requested`. Endpoints: `POST /deliverables/{id}/submit-review`, `POST /deliverables/{id}/approve`, `POST /deliverables/{id}/request-changes {comment}`. | 1 week | 1.1 |
| **1.6** | **Brand Kit Entity + Logo Overlay** — `brand_kits` table (tenant_id, name, logo_path, palette, font). Upload logo via API → stored → overlaid in `stage_motion_graphics` using FFmpeg overlay filter. | 1 week | None |
| **1.7** | **Multi-language TTS** — Pass `brief.language` to edge-tts voice selector (e.g., `bn-BD-NabanitaNeural` for Bangla). Add voice mapping table. Caption font auto-selects based on script detection. | 2 days | None |

**Total Phase 1 effort:** ~6–7 weeks (1 full-stack developer)

### Phase 2 — Agency Operations (P1)

| Step | What to Build | Est. Effort |
|---|---|---|
| **2.1** | Client entity (`clients` table under tenants) + client CRUD + assign projects to clients | 3 days |
| **2.2** | Campaign entity (`campaigns` table: tenant_id, client_id, name, objective, start/end date) + group projects | 3 days |
| **2.3** | Notification system (email via SMTP/SendGrid + in-app notification bell) triggered on job.completed, approval.required | 1 week |
| **2.4** | Scene-level editor (reorder scenes, swap image, adjust duration) — API + UI | 2 weeks |
| **2.5** | Revision history with diff viewer | 1 week |
| **2.6** | Agency dashboard (charts: videos/month, spend, active campaigns, pending approvals, avg turnaround) | 1 week |
| **2.7** | Team activity feed | 3 days |

**Total Phase 2:** ~5–6 weeks

### Phase 3 — Advanced (P2–P3)

| Step | What to Build |
|---|---|
| 3.1 | Comment/annotation on video timeline (timestamped feedback) |
| 3.2 | Custom font upload + rendering |
| 3.3 | Intro/outro template builder |
| 3.4 | Pricing models + invoicing |
| 3.5 | CSV/PDF export |
| 3.6 | Mobile-responsive PWA |
| 3.7 | Distributed rate limiter (Redis-backed instead of in-memory) |
| 3.8 | Live generative video via ComfyUI integration |

---

## 6. STEP-BY-STEP: CURRENT STATE → PRODUCTION-GRADE AGENCY PLATFORM

```
CURRENT STATE
    │
    ├── Backend engine: ✅ DONE (20-stage pipeline, QA, repair, multi-tenant, security)
    ├── API: ✅ DONE (32 routes)
    ├── CI/CD: ✅ DONE
    ├── Docs: ✅ DONE
    │
    ▼
PHASE 1: MINIMUM VIABLE AGENCY PLATFORM (P0)
    │
    ├── [1.1] Build web frontend ────────────────── Next.js + Tailwind + shadcn/ui
    ├── [1.2] Video preview player ─────────────── signed URLs + <video> tag
    ├── [1.3] Human authentication ─────────────── JWT + bcrypt (keep API keys for M2M)
    ├── [1.4] Script revision endpoint ─────────── PATCH + version bump + re-render
    ├── [1.5] Approval state machine ───────────── draft→review→approved/rejected
    ├── [1.6] Brand kit + logo overlay ──────────── FFmpeg overlay in motion_graphics stage
    └── [1.7] Multi-language TTS ───────────────── edge-tts voice mapping per language
    │
    ▼ ← At this point: USABLE BY A REAL AGENCY (account manager + client can interact)
    │
PHASE 2: AGENCY OPERATIONS (P1)
    │
    ├── [2.1] Client entity (sub-tenant)
    ├── [2.2] Campaign entity
    ├── [2.3] Email + in-app notifications
    ├── [2.4] Scene-level editor
    ├── [2.5] Revision history + diff
    ├── [2.6] Agency dashboard (analytics)
    └── [2.7] Activity feed
    │
    ▼ ← At this point: FULL-FEATURED DIGITAL MARKETING AGENCY PLATFORM
    │
PHASE 3: ADVANCED (P2-P3)
    ├── Timestamped comments on video
    ├── Custom fonts, intro/outro builder
    ├── Pricing + invoicing
    ├── CSV/PDF reports
    ├── Redis rate limiter
    └── ComfyUI GPU generative video
    │
    ▼ ← ENTERPRISE-GRADE INTERNATIONAL DIGITAL MARKETING AGENCY
```

---

## 7. UI/UX REQUIREMENTS (When Frontend Is Built)

To meet "international level" standards:

| Requirement | Specification |
|---|---|
| Framework | Next.js 14+ App Router, React Server Components where possible |
| Styling | Tailwind CSS + shadcn/ui (accessible, themeable, dark mode built-in) |
| Design system | Consistent spacing scale, typography hierarchy, color tokens mapped to brand palettes |
| Layout | Responsive: mobile-first, sidebar nav on desktop, bottom tab on mobile |
| Video player | Custom controls (play/pause/scrub/volume/fullscreen/picture-in-picture), keyboard accessible |
| Forms | Real-time validation, inline errors, disabled states during submit, optimistic updates |
| Loading states | Skeleton screens (not spinners) for lists, progressive image loading |
| Empty states | Helpful illustrations + CTA ("Create your first project") |
| Error states | Human-readable messages with retry action, never raw stack traces |
| Toasts | Non-blocking success/error notifications, auto-dismiss with manual close |
| Tables | Sortable columns, column visibility toggle, CSV export, sticky header, row selection |
| Charts | Recharts or Chart.js for dashboard analytics |
| Accessibility | WCAG 2.1 AA minimum: semantic HTML, aria-labels, focus trap in modals, keyboard navigation, contrast ≥4.5:1 |
| Dark mode | System preference detection + manual toggle, persisted |
| i18n | next-intl or similar; Bangla + English from day 1; RTL-ready structure |
| Performance | Lighthouse ≥90, lazy-load images/video, code splitting, ISR for static pages |
| Auth pages | Clean split-screen (form left, illustration right), social login optional |

---

## 8. BACKEND GAPS THAT MUST BE CLOSED BEFORE FRONTEND CAN WORK

The frontend needs these API additions (currently missing):

| Missing API | Purpose | Method |
|---|---|---|
| `POST /auth/register` | User signup (email+password) | JWT issued |
| `POST /auth/login` | User login | Returns access+refresh token |
| `POST /auth/refresh` | Token refresh | New access token |
| `GET /auth/me` | Current user profile | Role, tenant, permissions |
| `PATCH /v1/projects/{id}` | Update project name/brief | Triggers re-validation |
| `PATCH /v1/projects/{id}/script` | Edit script sections → re-render | Creates new version |
| `POST /v1/projects/{id}/reorder-scenes` | Reorder storyboard scenes | Updates EDL |
| `POST /v1/brand-kits` | Create/upload brand kit (logo, palette, font) | Stored per tenant |
| `GET /v1/brand-kits` | List brand kits for tenant | For dropdown in brief form |
| `POST /v1/deliverables/{id}/approve` | Approve a deliverable | Moves state machine |
| `POST /v1/deliverables/{id}/request-changes` | Reject with comment | Creates revision task |
| `GET /v1/notifications` | List user's notifications | Unread count included |
| `PATCH /v1/notifications/read` | Mark read | Bulk support |
| `GET /v1/dashboard/stats` | Agency overview data | Aggregated counts |

---

## 9. AGENCY SOP CHECKLIST — What The System Must Support

| SOP Step | Currently Supported? | Gap |
|---|---|---|
| Client onboarding | ❌ | No client entity, no onboarding flow |
| Brief collection | ⚠️ API only | Need web form + validation + file upload UI |
| Creative briefing | ⚠️ Key points exist | Need structured template + attachment |
| Concept/script approval | ❌ | No approval state machine for scripts |
| Production | ✅ Fully automated | Works |
| Internal review | ❌ | No review UI, no status tracking |
| Client review | ❌ | No client portal or share link |
| Revision cycle | ❌ | No revision endpoint |
| Final approval | ⚠️ Binary gate exists | Needs per-deliverable granularity |
| Delivery/export | ✅ Variants + manifest | Needs client-facing delivery page |
| Reporting | ⚠️ Cost + events only | Needs agency dashboard |
| Billing | ❌ | Not built |
| Archive | ⚠️ Cleanup CLI exists | Needs per-project archive flag |

---

## 10. SUMMARY — Path From Current State To Goal

**Current state:** Powerful backend engine (84/100 engineering score). Usable only by developers via API calls.

**Missing to become enterprise digital marketing agency:**
1. A **frontend** so humans can interact with it (biggest gap)
2. **Human authentication** (JWT login, not just API keys)
3. **Revision workflow** (edit → re-render without starting over)
4. **Approval state machine** (formal client sign-off)
5. **Brand kit persistence** (logo, fonts, colors per client)
6. **Multi-language TTS wiring** (Bangla support)
7. **Campaign/client entities** (organizational structure)
8. **Notifications** (email + in-app)
9. **Agency dashboard** (business overview)
10. **Billing** (monetization)

**Estimated total effort:** ~12 weeks (1 senior full-stack developer) for Phases 1+2, making it a genuinely usable enterprise agency platform. Phase 3 adds polish and advanced features.

---

*This report is based on actual code inspection (32 routes audited, 20 stages reviewed, all capability modules examined) and real usage simulation (attempting to perform agency tasks through the existing API).*
