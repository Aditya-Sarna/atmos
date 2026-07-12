const vscode = require("vscode");
const fs = require("fs");
const path = require("path");

const IGNORE_DIRS = new Set(["node_modules", ".git", "dist", "build", ".next", "__pycache__", "venv", ".venv"]);
const IGNORE_EXT = new Set([".png", ".jpg", ".gif", ".webp", ".lock", ".woff", ".woff2"]);
const MAX_FILES = 120;
const MAX_BYTES = 80000;
const EXT_VERSION = "0.2.1";

let bridgeTimer = null;
let statusBar = null;
let lastModels = [];
let lastModelObjs = [];
let bridgeBusy = false;
let lastError = "";
let promptedThisSession = false;

function getConfig() {
  const c = vscode.workspace.getConfiguration("atmos");
  let ide = c.get("ide") || "auto";
  if (ide === "auto") {
    const app = (vscode.env.appName || "").toLowerCase();
    if (app.includes("cursor")) ide = "cursor";
    else if (app.includes("claude")) ide = "claude";
    else ide = "vscode";
  }
  return {
    backendUrl: c.get("backendUrl") || "http://localhost:8000",
    projectId: c.get("projectId") || "",
    useNativeIdeLlm: c.get("useNativeIdeLlm") !== false,
    preferredModel: (c.get("preferredModel") || "").trim(),
    preferredVisionModel: (c.get("preferredVisionModel") || "").trim(),
    promptForModelOnConnect: c.get("promptForModelOnConnect") !== false,
    ide,
    enableDopamineMax: c.get("enableDopamineMax") === true,
    pageUrl: c.get("pageUrl") || "",
  };
}

function modelLabel(m) {
  return `${m.vendor}/${m.family || m.name || m.id || "model"}`;
}

async function apiFetch(cfg, method, route, body) {
  const url = `${cfg.backendUrl.replace(/\/$/, "")}/api${route}`;
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

function setStatus(text, tooltip) {
  if (!statusBar) return;
  statusBar.text = text;
  statusBar.tooltip = tooltip || text;
}

async function listIdeModels() {
  if (!vscode.lm || typeof vscode.lm.selectChatModels !== "function") {
    return [];
  }
  try {
    const models = await vscode.lm.selectChatModels({});
    lastModelObjs = models || [];
    return lastModelObjs;
  } catch (e) {
    lastError = String(e.message || e);
    lastModelObjs = [];
    return [];
  }
}

async function savePreferred(key, value) {
  await vscode.workspace.getConfiguration("atmos").update(key, value, vscode.ConfigurationTarget.Global);
}

async function selectModelInteractive({ vision = false, force = false } = {}) {
  const models = await listIdeModels();
  if (!models.length) {
    vscode.window.showWarningMessage(
      "Atmos: No IDE chat models found. Sign into Copilot / Cursor / Claude, then try again.",
    );
    return null;
  }
  const cfg = getConfig();
  const current = vision ? cfg.preferredVisionModel : cfg.preferredModel;
  const items = models.map((m) => {
    const label = modelLabel(m);
    const isCurrent = current && label.toLowerCase().includes(current.toLowerCase());
    return {
      label: isCurrent ? `$(check) ${label}` : label,
      description: m.vendor,
      detail: vision ? "Used for screenshot / vision Atmos jobs" : "Default model for Atmos text jobs",
      model: m,
      id: label,
    };
  });
  items.unshift({
    label: "$(sparkle) Auto (Atmos picks best available)",
    description: "Clear preference",
    detail: "Heuristic: gpt-4o / claude / gemini when present",
    model: null,
    id: "",
  });

  const picked = await vscode.window.showQuickPick(items, {
    title: vision ? "Atmos: Select vision model" : "Atmos: Select default IDE model",
    placeHolder: force
      ? "Pick which model Atmos should use from your IDE quota"
      : "Choose a model (uses your Copilot/Cursor/Claude entitlement)",
    matchOnDescription: true,
    matchOnDetail: true,
  });
  if (picked === undefined) return current || null;

  const value = picked.id || "";
  if (vision) {
    await savePreferred("preferredVisionModel", value);
  } else {
    await savePreferred("preferredModel", value);
  }
  await heartbeat();
  vscode.window.showInformationMessage(
    value
      ? `Atmos will use ${value} for ${vision ? "vision" : "default"} jobs`
      : `Atmos will auto-pick ${vision ? "vision" : "default"} models`,
  );
  return value || null;
}

async function maybePromptForModel() {
  const cfg = getConfig();
  if (!cfg.promptForModelOnConnect || promptedThisSession) return;
  if (cfg.preferredModel) return;
  const models = await listIdeModels();
  if (models.length < 2) {
    if (models.length === 1 && !cfg.preferredModel) {
      await savePreferred("preferredModel", modelLabel(models[0]));
    }
    return;
  }
  promptedThisSession = true;
  const choice = await vscode.window.showInformationMessage(
    `Atmos found ${models.length} IDE models. Pick which one should fund Atmos runs?`,
    "Select model",
    "Auto",
    "Don't ask again",
  );
  if (choice === "Select model") {
    await selectModelInteractive({ force: true });
  } else if (choice === "Don't ask again") {
    await vscode.workspace.getConfiguration("atmos").update(
      "promptForModelOnConnect",
      false,
      vscode.ConfigurationTarget.Global,
    );
  }
}

async function heartbeat() {
  const cfg = getConfig();
  if (!cfg.useNativeIdeLlm) {
    setStatus("$(circle-slash) Atmos LLM off", "Native IDE LLM disabled in settings");
    return;
  }
  const models = await listIdeModels();
  lastModels = models.map(modelLabel);
  const supportsVision = models.some((m) => {
    try {
      return Array.isArray(m.capabilities?.imageInput) || m.capabilities?.vision || false;
    } catch {
      return false;
    }
  });
  try {
    await apiFetch(cfg, "POST", "/ide/llm/heartbeat", {
      ide: cfg.ide,
      models: lastModels,
      supports_vision: supportsVision,
      extension_version: EXT_VERSION,
      preferred_model: cfg.preferredModel || null,
      preferred_vision_model: cfg.preferredVisionModel || null,
    });
    const pref = cfg.preferredModel || "auto";
    const short = pref.length > 28 ? `${pref.slice(0, 26)}…` : pref;
    setStatus(
      `$(hubot) Atmos · ${short}`,
      [
        `IDE: ${cfg.ide}`,
        `Default model: ${cfg.preferredModel || "(auto)"}`,
        `Vision model: ${cfg.preferredVisionModel || "(same / auto)"}`,
        `Available (${lastModels.length}):`,
        ...lastModels.map((m) => `  • ${m}`),
        "",
        "Click status → Select model, or run Atmos: Select default IDE model",
      ].join("\n"),
    );
    lastError = lastModels.length ? "" : "No vscode.lm chat models available";
  } catch (e) {
    lastError = String(e.message || e);
    setStatus("$(warning) Atmos bridge offline", lastError);
  }
}

function pickModel(models, hint) {
  if (!models.length) return null;
  const cfg = getConfig();
  const candidates = [hint, cfg.preferredModel, cfg.preferredVisionModel].filter(Boolean);
  for (const raw of candidates) {
    const h = String(raw).toLowerCase();
    const hit = models.find((m) => modelLabel(m).toLowerCase().includes(h) || h.includes(modelLabel(m).toLowerCase()));
    if (hit) return hit;
    const soft = models.find((m) =>
      `${m.vendor} ${m.family || ""} ${m.name || ""} ${m.id || ""}`.toLowerCase().includes(h),
    );
    if (soft) return soft;
  }
  const prefer = ["gpt-4o", "claude", "sonnet", "opus", "gemini", "gpt-4"];
  for (const p of prefer) {
    const hit = models.find((m) =>
      `${m.family || ""} ${m.name || ""}`.toLowerCase().includes(p),
    );
    if (hit) return hit;
  }
  return models[0];
}

async function runJobWithIdeModel(job) {
  const models = await listIdeModels();
  const hasImages = (job.images_b64 || []).length > 0;
  const cfg = getConfig();
  const hint = hasImages
    ? (job.model_hint || cfg.preferredVisionModel || cfg.preferredModel)
    : (job.model_hint || cfg.preferredModel);
  const model = pickModel(models, hint);
  if (!model) {
    throw new Error(
      "No IDE language models available via vscode.lm. Sign into GitHub Copilot, Cursor, or Claude in this IDE.",
    );
  }

  const parts = [];
  const images = job.images_b64 || [];
  if (images.length && vscode.LanguageModelDataPart) {
    for (const b64 of images.slice(0, 3)) {
      try {
        const buf = Buffer.from(b64, "base64");
        parts.push(vscode.LanguageModelDataPart.image(new Uint8Array(buf), "image/png"));
      } catch {
        /* skip */
      }
    }
  }
  const userText = [
    job.system ? `System instructions:\n${job.system}\n` : "",
    job.prompt || "",
    job.expect_json ? "\n\nRespond with valid JSON only." : "",
    images.length && !parts.length
      ? `\n\n(${images.length} screenshot(s) were attached but this IDE model path could not accept images — reason from the text context.)`
      : "",
  ].join("\n");

  if (parts.length) parts.push(userText);

  const messages = [
    vscode.LanguageModelChatMessage.User(parts.length ? parts : userText),
  ];

  const cts = new vscode.CancellationTokenSource();
  const timeout = setTimeout(() => cts.cancel(), 170000);
  try {
    const response = await model.sendRequest(messages, {}, cts.token);
    let text = "";
    for await (const fragment of response.text) {
      text += fragment;
    }
    return {
      result_text: text,
      model_used: modelLabel(model),
    };
  } finally {
    clearTimeout(timeout);
    cts.dispose();
  }
}

async function pollJobsOnce() {
  if (bridgeBusy) return;
  const cfg = getConfig();
  if (!cfg.useNativeIdeLlm) return;
  bridgeBusy = true;
  try {
    const data = await apiFetch(cfg, "GET", "/ide/llm/jobs/pending?limit=2");
    const jobs = data.jobs || [];
    for (const job of jobs) {
      setStatus(`$(sync~spin) Atmos · ${job.purpose || "LLM"}…`, job.model_hint || job.job_id);
      try {
        const out = await runJobWithIdeModel(job);
        await apiFetch(cfg, "POST", `/ide/llm/jobs/${job.job_id}/complete`, out);
      } catch (e) {
        await apiFetch(cfg, "POST", `/ide/llm/jobs/${job.job_id}/complete`, {
          error: String(e.message || e),
        });
        lastError = String(e.message || e);
      }
    }
  } catch (e) {
    lastError = String(e.message || e);
  } finally {
    bridgeBusy = false;
  }
}

function startBridge(context) {
  if (bridgeTimer) return;
  const tick = async () => {
    await heartbeat();
    await pollJobsOnce();
  };
  tick();
  bridgeTimer = setInterval(tick, 2500);
  context.subscriptions.push({ dispose: () => clearInterval(bridgeTimer) });
}

function walkWorkspace(root) {
  const files = [];
  function walk(dir) {
    if (files.length >= MAX_FILES) return;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (files.length >= MAX_FILES) break;
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (!IGNORE_DIRS.has(e.name) && !e.name.startsWith(".")) walk(full);
      } else if (e.isFile()) {
        const ext = path.extname(e.name).toLowerCase();
        if (IGNORE_EXT.has(ext)) continue;
        try {
          const stat = fs.statSync(full);
          const rel = path.relative(root, full);
          const content = stat.size <= MAX_BYTES * 2
            ? fs.readFileSync(full, "utf8").slice(0, MAX_BYTES)
            : "";
          files.push({ path: rel, size: stat.size, content, truncated: stat.size > MAX_BYTES });
        } catch { /* skip */ }
      }
    }
  }
  walk(root);
  return files;
}

async function syncCodebase() {
  const cfg = getConfig();
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    vscode.window.showErrorMessage("Atmos: Open a workspace folder first.");
    return;
  }
  const editor = vscode.window.activeTextEditor;
  const files = walkWorkspace(folder.uri.fsPath);
  await apiFetch(cfg, "POST", "/ide/context", {
    workspace_root: folder.uri.fsPath,
    workspace_name: folder.name,
    open_file: editor ? path.relative(folder.uri.fsPath, editor.document.uri.fsPath) : null,
    selection: editor ? editor.document.getText(editor.selection) : null,
    page_url: cfg.pageUrl || null,
    files,
  });
  await apiFetch(cfg, "PUT", "/ide/llm-config", {
    enabled: true,
    mode: "ide_native",
    model: cfg.preferredModel || lastModels[0] || "ide-default",
    preferred_model: cfg.preferredModel || null,
    preferred_vision_model: cfg.preferredVisionModel || null,
    provider: "ide_native",
  });
  await heartbeat();
  vscode.window.showInformationMessage(
    `Atmos: synced ${files.length} files · model ${cfg.preferredModel || "auto"}`,
  );
}

async function generatePlan() {
  const cfg = getConfig();
  if (!cfg.projectId) {
    const id = await vscode.window.showInputBox({ prompt: "Atmos project ID" });
    if (!id) return;
    cfg.projectId = id;
  }
  await syncCodebase();
  const plan = await apiFetch(cfg, "POST", `/projects/${cfg.projectId}/test-plans/generate`, {
    command: "/atmos test",
    page_url: cfg.pageUrl || undefined,
  });
  const doc = await vscode.workspace.openTextDocument({
    content: JSON.stringify(plan, null, 2),
    language: "json",
  });
  await vscode.window.showTextDocument(doc);
}

async function startRun() {
  const cfg = getConfig();
  if (!cfg.projectId) {
    vscode.window.showErrorMessage("Set atmos.projectId in settings");
    return;
  }
  await heartbeat();
  const r = await apiFetch(cfg, "POST", `/projects/${cfg.projectId}/runs`, {
    command: "/atmos test",
    enable_dopamine_max: cfg.enableDopamineMax,
  });
  const dash = cfg.backendUrl.replace(/\/api\/?$/, "");
  vscode.env.openExternal(vscode.Uri.parse(`${dash}/runs/${r.run_id}`));
}

async function selectChaosTargets() {
  const cfg = getConfig();
  if (!cfg.projectId) {
    vscode.window.showErrorMessage("Set atmos.projectId in settings");
    return;
  }
  const scopePick = await vscode.window.showQuickPick(
    [
      { label: "$(globe) Entire app", description: "Stress all discovered / home routes", id: "app" },
      { label: "$(file) Selected pages", description: "Pick paths or URLs", id: "pages" },
    ],
    { title: "Atmos Chaos Lab — scope" },
  );
  if (!scopePick) return;

  let pages = [];
  let includePayments = false;
  if (scopePick.id === "pages") {
    const raw = await vscode.window.showInputBox({
      prompt: "Comma-separated paths or URLs (e.g. /checkout, /pricing, http://localhost:3000/pay)",
      value: cfg.pageUrl || "/",
      placeHolder: "/, /checkout, /login",
    });
    if (raw == null) return;
    pages = raw.split(",").map((s) => s.trim()).filter(Boolean);
  }
  const pay = await vscode.window.showQuickPick(
    [
      { label: "Include payment field probes", id: "yes" },
      { label: "Skip payments", id: "no" },
    ],
    { title: "Probe Stripe/PayPal-style card fields on payment pages?" },
  );
  includePayments = pay?.id === "yes";

  await apiFetch(cfg, "PUT", `/projects/${cfg.projectId}/chaos/targets`, {
    scope: scopePick.id,
    pages,
    include_payments: includePayments,
    source: "ide",
  });
  await vscode.workspace.getConfiguration("atmos").update(
    "chaosScope",
    scopePick.id,
    vscode.ConfigurationTarget.Global,
  );
  vscode.window.showInformationMessage(
    `Atmos Chaos targets saved · ${scopePick.id}${pages.length ? ` · ${pages.length} page(s)` : ""}`,
  );
}

async function startChaosFromIde({ mode = "crash" } = {}) {
  const cfg = getConfig();
  if (!cfg.projectId) {
    vscode.window.showErrorMessage("Set atmos.projectId in settings");
    return;
  }
  await heartbeat();
  await syncCodebase().catch(() => {});

  let targets = { scope: "app", pages: [], include_payments: true };
  try {
    targets = await apiFetch(cfg, "GET", `/projects/${cfg.projectId}/chaos/targets`);
  } catch { /* defaults */ }

  const startUsers = await vscode.window.showInputBox({
    prompt: mode === "crash" ? "Crash test — starting user count" : "Fixed concurrent users",
    value: mode === "crash" ? "25" : "50",
    validateInput: (v) => (/^\d+$/.test(v) && Number(v) >= 5 ? null : "Enter a number ≥ 5"),
  });
  if (!startUsers) return;

  let maxUsers = startUsers;
  if (mode === "crash") {
    const mx = await vscode.window.showInputBox({
      prompt: "Ramp until break — max users",
      value: "200",
      validateInput: (v) => (/^\d+$/.test(v) && Number(v) >= Number(startUsers) ? null : "Must be ≥ start users"),
    });
    if (!mx) return;
    maxUsers = mx;
  }

  const run = await apiFetch(cfg, "POST", `/projects/${cfg.projectId}/runs`, {
    command: "/atmos test",
    enable_dopamine_max: cfg.enableDopamineMax,
  });
  await apiFetch(cfg, "POST", `/runs/${run.run_id}/chaos/start`, {
    scope: targets.scope || "app",
    pages: targets.pages || [],
    mode,
    users: Number(startUsers),
    max_users: Number(maxUsers),
    hold_secs: 10,
    include_payments: !!targets.include_payments,
    payment_provider: "stripe",
    step_factor: 2,
  });

  const dash = cfg.backendUrl.replace(/\/api\/?$/, "");
  vscode.env.openExternal(vscode.Uri.parse(`${dash}/runs/${run.run_id}?tab=chaos`));
  vscode.window.showInformationMessage(
    mode === "crash"
      ? `Crash test started · ${startUsers} → ${maxUsers} until break`
      : `Fixed load started · ${startUsers} users`,
  );
}

function activate(context) {
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.command = "atmos.selectModel";
  statusBar.show();
  context.subscriptions.push(statusBar);

  context.subscriptions.push(
    vscode.commands.registerCommand("atmos.syncCodebase", syncCodebase),
    vscode.commands.registerCommand("atmos.generatePlan", generatePlan),
    vscode.commands.registerCommand("atmos.startRun", startRun),
    vscode.commands.registerCommand("atmos.selectChaosTargets", selectChaosTargets),
    vscode.commands.registerCommand("atmos.startCrashTest", () => startChaosFromIde({ mode: "crash" })),
    vscode.commands.registerCommand("atmos.startChaosFixed", () => startChaosFromIde({ mode: "fixed" })),
    vscode.commands.registerCommand("atmos.selectModel", () => selectModelInteractive({ force: true })),
    vscode.commands.registerCommand("atmos.selectVisionModel", () =>
      selectModelInteractive({ vision: true, force: true }),
    ),
    vscode.commands.registerCommand("atmos.connectIdeLlm", async () => {
      startBridge(context);
      await heartbeat();
      await maybePromptForModel();
      const cfg = getConfig();
      vscode.window.showInformationMessage(
        lastModels.length
          ? `Atmos connected · using ${cfg.preferredModel || "auto"} (${lastModels.length} available)`
          : "Atmos bridge started, but no IDE models were listed. Sign in to Copilot/Cursor/Claude chat models.",
      );
    }),
    vscode.commands.registerCommand("atmos.showIdeLlmStatus", async () => {
      const cfg = getConfig();
      const msg = [
        `IDE: ${cfg.ide}`,
        `Default model: ${cfg.preferredModel || "(auto)"}`,
        `Vision model: ${cfg.preferredVisionModel || "(same / auto)"}`,
        `Available: ${lastModels.join(", ") || "(none)"}`,
        lastError ? `Last error: ${lastError}` : "OK",
      ].join("\n");
      const pick = await vscode.window.showInformationMessage(msg, "Select model", "Select vision model");
      if (pick === "Select model") await selectModelInteractive({ force: true });
      if (pick === "Select vision model") await selectModelInteractive({ vision: true, force: true });
    }),
    vscode.commands.registerCommand("atmos.openDashboard", () => {
      const cfg = getConfig();
      const dash = cfg.backendUrl.replace(/\/api\/?$/, "");
      vscode.env.openExternal(vscode.Uri.parse(`${dash}/dashboard`));
    }),
  );

  if (getConfig().useNativeIdeLlm) {
    startBridge(context);
    setTimeout(() => { maybePromptForModel().catch(() => {}); }, 1500);
  }
}

function deactivate() {
  if (bridgeTimer) clearInterval(bridgeTimer);
}

module.exports = { activate, deactivate };
