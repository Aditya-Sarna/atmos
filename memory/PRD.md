# Atmos — Autonomous Product Testing & UX Intelligence Agent

## Mission
A SaaS dashboard that watches your web app like a real user — analyzes archetype, plans context-aware tests, explores autonomously, performs each test case live on a mocked UI, surfaces issues with **before/after visual diffs + alternative fixes**, benchmarks vs industry leaders, and produces an executive report.

## Users
- Engineers / designers who want a second pair of (autonomous) eyes on the product.
- PMs / leads who want a single executive report with concrete recommendations.

## Architecture
- **Backend**: FastAPI + MongoDB. SSE for live runs. Claude Sonnet 4.5 via `emergentintegrations` for context-aware plan + executive report. Emergent Auth (Google) for sign-in.
- **Frontend**: React + Tailwind + Shadcn. Apple-like aesthetic (Outfit/Manrope, #1D1D1F ink, #0071E3 blue accent). Visual mocks are CSS-only Scene components.

## Implemented (Feb 2026)
### v1
- Marketing landing, Emergent Google login, Dashboard, New-run wizard, Live RunMonitor (SSE), Executive Report.
- 10 `/atmos` commands. 7 personas. 8 viewports. Per-issue scores (accessibility / UX / reliability).
- Claude Sonnet 4.5 plan + report generation, with deterministic fallback.

### v2 — Visual diffs + Live test case playback (current)
- Each issue now ships with a `scene` + `before` + `after` (executed fix with code snippet) + 2 `alternatives` (each rendered as a CSS scene variant the user can preview by click).
- New `test_cases` phase: every test case Atmos performs is emitted live as `test_case` / `test_case_step` events. Frontend renders a checklist + a "Theatre" with `ScenePlayer` recording the step-by-step playback.
- RunMonitor reorganized into 3 tabs: Live capture, Test cases (N), Issues (N).
- Report page renders all `IssueDiffCard`s with alternatives + recorded test cases.

## Backlog (P1 → P2)
- P1: Real Playwright execution against a user URL (replace simulated engine).
- P1: Re-runs against a saved baseline → visual diff highlighting actual regressions.
- P1: Export executive report to PDF.
- P2: Slack / Linear integration to file each issue as a ticket with before/after attached.
- P2: VS Code / Cursor plugin entry point invoking the same backend.

## Files
- Backend: `/app/backend/server.py` (1.1k lines).
- Frontend: `/app/frontend/src/pages/{Landing,Login,Dashboard,NewRun,RunMonitor,Report,AuthCallback}.jsx`.
- Components: `Scene.jsx`, `IssueDiffCard.jsx`, `TestCases.jsx`, `SiteHeader.jsx`, `BenchmarkMarquee.jsx`, `AtmosMark.jsx`, `ProtectedRoute.jsx`.

## Test credentials
See `/app/memory/test_credentials.md` and `/app/auth_testing.md`.
