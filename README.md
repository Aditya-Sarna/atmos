# Atmos

Autonomous UX / product-craft testing agent (FastAPI + React + MongoDB + Playwright).

## Local development

```bash
./start-local.sh
```

- App: http://localhost:3000/dashboard  
- API: http://localhost:8000/api/  
- Health: http://localhost:8000/api/health/ready  

**Auth:** create an account at `/login` (email + password) or use `ATMOS_DISABLE_AUTH=1` for local bypass.  
**LLM:** keep the Atmos IDE extension open in Cursor/VS Code so analysis runs on your IDE model quota (no Atmos API key).

## Docker

```bash
docker compose up --build
```

Set `ATMOS_ENV=production` and `ATMOS_DISABLE_AUTH=0`. Prefer the IDE LLM bridge (`ATMOS_ALLOW_EMERGENT_FALLBACK=0`).

## Slash commands

Each command runs a specialized profile (not one identical pipeline):

| Command | Focus |
|---------|--------|
| `/atmos test` | Full suite |
| `/atmos accessibility` | Deep a11y + personas |
| `/atmos mobile` | Mobile viewports + personas |
| `/atmos benchmark` | Funnel, competitive, demand, copy |
| `/atmos personas` | All human personas |
| `/atmos explore` | Journey discovery |
| `/atmos regress` | Fuzz + screen/custom tests |
| `/atmos analyze` | Design + vision + architecture |
| `/atmos report` | Executive intelligence pack |
| `/atmos record` | Capture-heavy recording |

## Quality bar

- **Craft Score** — canonical 0–100 system of record (a11y, personas, UX, design, funnel, competitive)
- Baseline Δ vs previous completed run + merge **craft gate** (`GET /api/projects/{id}/craft/gate`)
- GitHub Action: `integrations/github-actions/atmos-craft-gate.yml`
- Real accessibility audit (contrast, ARIA names, landmarks, keyboard tab order)
- Plan/test cases executed with Playwright + video (not sleep theater)
- Demand research: keyword plan → scrape → insight markdown
- LLM via user’s IDE models (`vscode.lm`) with model picker
- First-party email/password auth for production
- Health/ready probes, rate limiting, Docker Compose, CI syntax/build checks

## Chaos Lab

Architecture-aware live stress replaced the old swarm/payment theater:

- **Scope:** entire app or selected pages (UI picker or IDE)
- **Modes:** fixed concurrency, or **crash test** (ramp until success/p95 break)
- **Hybrid load:** HTTP volume + Playwright sample journeys
- **Live diagram:** client → edge → routes → API → data/payments health stream
- **Payments:** real browser fills of Stripe test cards on checkout-like pages

IDE commands (extension v0.3.0):

- `Atmos: Select pages / entire app for Chaos Lab`
- `Atmos: Start crash test (ramp until break)`
- `Atmos: Start fixed load test`

API: `PUT /projects/{id}/chaos/targets`, `POST /runs/{id}/chaos/start`, `GET /runs/{id}/chaos/live`
