# Atmos IDE extension

Funds Atmos LLM work from **your IDE model quota** (GitHub Copilot, Cursor, Claude in VS Code) via `vscode.lm`. You do **not** paste an API key.

## How it works

1. Install this folder as a VS Code / Cursor extension (`Developer: Install Extension from Location…` or symlink into `~/.cursor/extensions` / `~/.vscode/extensions`).
2. Set `atmos.backendUrl` (default `http://localhost:8000`) and `atmos.projectId`.
3. Command **Atmos: Connect IDE models** (also starts automatically on launch).
4. Status bar shows your selected model when the bridge is online.
5. When you start a run in Atmos, the backend enqueues LLM jobs; this extension runs them with `vscode.lm.selectChatModels()` / `sendRequest()` and posts results back — billed to **your** Copilot/Cursor/Claude entitlement.

## Pick a model

Atmos can use any chat model your IDE exposes via `vscode.lm`.

1. **Atmos: Select default IDE model** — QuickPick of available models (saved to `atmos.preferredModel`)
2. **Atmos: Select vision IDE model** — optional separate pick for screenshot jobs (`atmos.preferredVisionModel`)
3. On connect, if nothing is saved and multiple models exist, Atmos prompts: *Select model / Auto / Don't ask again*
4. Status bar shows the active preference — click it to change

Jobs from the backend carry a `model_hint`; the extension matches it to your pick, then falls back to auto heuristics (gpt-4o / claude / gemini).

## Requirements

- VS Code ≥ 1.90 **or** Cursor (VS Code fork)
- At least one chat model available in the IDE (Copilot signed in, Cursor models enabled, etc.)
- Atmos backend running with auth bypass for local (`ATMOS_DISABLE_AUTH=1`) or a logged-in session cookie

## Settings

| Setting | Purpose |
|---------|---------|
| `atmos.backendUrl` | Backend origin |
| `atmos.projectId` | Project to sync/run |
| `atmos.useNativeIdeLlm` | Default `true` — use IDE models, no key |
| `atmos.preferredModel` | Default model id/family |
| `atmos.preferredVisionModel` | Vision/screenshot model |
| `atmos.promptForModelOnConnect` | Prompt to pick a model when unset |
| `atmos.ide` | `auto` / `cursor` / `vscode` / `claude` |

Optional HTTP BYOK was removed from the happy path on purpose. Power users can still set `ATMOS_USER_LLM_*` on the server for CI.
