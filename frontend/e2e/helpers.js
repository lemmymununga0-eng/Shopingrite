// Starts, stops and restarts a REAL backend process for the browser tests (needed to prove that data
// survives a restart). Uses its own throw-away databases under backend/data/e2e/.
import { spawn, spawnSync } from "node:child_process";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(here, "..", "..");
export const BACKEND_DIR = path.join(ROOT, "backend");
export const E2E_DIR = path.join(BACKEND_DIR, "data", "e2e");
export const API = "http://127.0.0.1:8799";
export const WEB = "http://127.0.0.1:5199";
const PID_FILE = path.join(here, ".backend.pid");
export const DEMO_PASSWORD = "DemoPass!2026";

export function backendEnv() {
  const e = { ...process.env };
  for (const k of ["MODEL_THRESHOLD", "SAFE_BROWSING_API_KEY"]) delete e[k];
  return Object.assign(e, {
    ENVIRONMENT: "development", DB_BACKEND: "sqlite",
    SQLITE_PATH: path.join(E2E_DIR, "fraudguard.db"),
    DATABASE_URL: `sqlite:///${path.join(E2E_DIR, "app.db").replaceAll("\\", "/")}`,
    LOCAL_AUTH_ENABLED: "true", LOCAL_AUTH_SECRET: "e2e-only-local-secret-0123456789-abcdefghij",
    SUPABASE_URL: "", SUPABASE_ANON_KEY: "", SUPABASE_JWT_SECRET: "",
    SCAMWATCH_PROVIDERS: "heuristic,mock", SCAMWATCH_MOCK_VERDICTS: "bad.example=malicious",
    PREDICT_RATE_LIMIT_PER_MIN: "1000", CHECKOUT_RATE_LIMIT_PER_MIN: "1000", CART_RATE_LIMIT_PER_MIN: "1000",
    SCAMWATCH_RATE_LIMIT_PER_MIN: "1000", LOGIN_RATE_LIMIT_PER_MIN: "1000",
    CORS_ORIGINS: "http://127.0.0.1:5199,http://localhost:5199", PYTHONUNBUFFERED: "1",
    // the specs expect the small legacy catalogue (DEMO-* SKUs); the Zambian catalogue is covered by backend tests
    SEED_LEGACY_DEMO: "true", SEED_ZM_CATALOGUE: "false", STORE_IS_DEMO: "true", COD_ENABLED: "true",
    // real-payment journeys run against a local stand-in for Flutterwave (e2e/fake-flutterwave.mjs)
    FLW_SECRET_KEY: FAKE_FLW.key, FLW_WEBHOOK_HASH: FAKE_FLW.hash, FLW_BASE_URL: `${FAKE_FLW.url}/v3`, FRONTEND_URL: WEB,
  });
}

export const FAKE_FLW = { url: "http://127.0.0.1:8798", key: "FLWSECK_TEST-e2e", hash: "e2e-hook-hash" };
const FAKE_PID = path.join(here, ".fake-flw.pid");

export async function startFakeFlutterwave() {
  const child = spawn(process.execPath, [path.join(here, "fake-flutterwave.mjs")], {
    env: { ...process.env, FAKE_FLW_KEY: FAKE_FLW.key, FAKE_FLW_WEBHOOK_HASH: FAKE_FLW.hash }, stdio: "ignore", windowsHide: true });
  writeFileSync(FAKE_PID, String(child.pid));
  child.unref();
  const end = Date.now() + 15_000;
  while (Date.now() < end) {
    try { if ((await fetch(`${FAKE_FLW.url}/health`)).ok) return; } catch { /* not up yet */ }
    await new Promise(r => setTimeout(r, 200));
  }
  throw new Error("fake Flutterwave did not start");
}

export function stopFakeFlutterwave() {
  if (!existsSync(FAKE_PID)) return;
  const pid = Number(readFileSync(FAKE_PID, "utf8"));
  try {
    if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
    else process.kill(pid, "SIGTERM");
  } catch { /* already gone */ }
  rmSync(FAKE_PID, { force: true });
}

export function resetE2eData() {
  rmSync(E2E_DIR, { recursive: true, force: true });      // only this test-owned scratch folder
  mkdirSync(E2E_DIR, { recursive: true });
}

export async function waitHealthy(timeoutMs = 90_000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { const r = await fetch(`${API}/health`); if (r.ok) return; } catch { /* not up yet */ }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error("Backend did not become healthy in time (see backend/data/e2e/backend.log)");
}

export async function startBackend() {
  mkdirSync(E2E_DIR, { recursive: true });
  const log = openSync(path.join(E2E_DIR, "backend.log"), "a");
  const child = spawn("python", ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8799"],
    { cwd: BACKEND_DIR, env: backendEnv(), stdio: ["ignore", log, log], windowsHide: true, detached: false });
  closeSync(log);
  writeFileSync(PID_FILE, String(child.pid));
  child.unref();
  await waitHealthy();
}

export function stopBackend() {
  if (!existsSync(PID_FILE)) return;
  const pid = Number(readFileSync(PID_FILE, "utf8"));
  try {
    if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
    else process.kill(pid, "SIGTERM");
  } catch { /* already gone */ }
  rmSync(PID_FILE, { force: true });
}

export async function restartBackend() {
  stopBackend();
  await new Promise(r => setTimeout(r, 1500));
  await startBackend();
}

// ---- browser helpers ----
export async function signOut(page) {
  await page.goto("/login");
  await page.evaluate(() => sessionStorage.clear());
  await page.goto("/login");
}

export async function signInAs(page, label) {
  await signOut(page);
  await page.getByRole("button", { name: label }).click();
  await page.getByRole("button", { name: "Login" }).click();
  await page.waitForFunction(() => !!sessionStorage.getItem("fg_local_session"));   // sign-in finished
}

/** Remove everything from the signed-in customer's cart, so a test starts from "nothing in the cart" (product cards show a stepper otherwise). */
export async function emptyCart(page) {
  const cart = await api(page, "GET", "/cart");
  for (const line of cart.json?.items || []) await api(page, "DELETE", `/cart/items/${line.item_id}`);
}

export const token = page => page.evaluate(() => JSON.parse(sessionStorage.getItem("fg_local_session")).token);

export async function api(page, method, url, body) {
  const t = await token(page);
  const res = await page.request.fetch(`${API}${url}`, { method, headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" },
    data: body ? JSON.stringify(body) : undefined });
  let json = null;
  try { json = await res.json(); } catch { /* no body */ }
  return { status: res.status(), json };
}
