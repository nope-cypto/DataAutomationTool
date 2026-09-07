const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { launchDebugChrome } = require("./chrome-launch.cjs");
const { createCurlCache } = require("./curl-cache.cjs");
const { createLocalIo } = require("./local-io.cjs");
const { isAllowedExternalUrl, isAllowedInAppNavigation } = require("./navigation-policy.cjs");
const { openOrSelectStep0Workbook } = require("./step0-workbook.cjs");
const { createUserPaths } = require("./user-paths.cjs");

const DEV_FRONTEND_URL = process.env.DATA_AUTOMATION_FRONTEND_URL || "http://127.0.0.1:18138";
const BACKEND_URL = "http://127.0.0.1:18137";
const workerSessionSecret = crypto.randomBytes(32).toString("hex");
process.env.DATA_AUTOMATION_SESSION_SECRET = workerSessionSecret;
let backendProcess = null;
let mainWindow = null;
let isQuitting = false;

if (!app.requestSingleInstanceLock()) app.quit();

function projectRoot() {
  return path.resolve(__dirname, "..", "..");
}

function userPaths() {
  return createUserPaths({ app, env: process.env });
}

function workerPath() {
  return path.join(process.resourcesPath, "worker", "DataAutomationToolWorker.exe");
}

function backendHealth() {
  return new Promise((resolve) => {
    const request = http.get(`${BACKEND_URL}/api/health`, {
      timeout: 800,
      headers: { "X-Data-Automation-Session": workerSessionSecret },
    }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => {
        try {
          resolve(response.statusCode === 200 && JSON.parse(body).service === "data-automation-tool-worker");
        } catch {
          resolve(false);
        }
      });
    });
    request.once("timeout", () => { request.destroy(); resolve(false); });
    request.once("error", () => resolve(false));
  });
}

async function waitForBackend(timeoutMs = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await backendHealth()) return true;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

async function startBackend() {
  if (process.env.DATA_AUTOMATION_SKIP_BACKEND === "1") return true;
  const environment = {
    ...process.env,
    DATA_AUTOMATION_SESSION_SECRET: workerSessionSecret,
  };
  if (app.isPackaged) {
    backendProcess = spawn(workerPath(), [], {
      cwd: path.dirname(workerPath()),
      env: environment,
      stdio: "ignore",
      windowsHide: true,
    });
  } else {
    const python = process.env.DATA_AUTOMATION_WORKER_PYTHON || (process.platform === "win32" ? "python" : "python3");
    backendProcess = spawn(python, ["-m", "web_workbench.worker.run_worker"], {
      cwd: projectRoot(),
      env: environment,
      stdio: "ignore",
      windowsHide: true,
    });
  }
  backendProcess.once("error", () => {
    if (!isQuitting) dialog.showErrorBox("本地服务启动失败", "请确认 Python 依赖或重新安装程序。");
  });
  backendProcess.once("exit", () => {
    backendProcess = null;
    if (!isQuitting) dialog.showErrorBox("本地服务已停止", "请重启 资料自动化工具。");
  });
  return waitForBackend();
}

function stopBackend() {
  if (backendProcess && !backendProcess.killed) backendProcess.kill();
  backendProcess = null;
}

function postJobAction(action, jobId) {
  return new Promise((resolve) => {
    if (!/^[0-9a-f-]{36}$/i.test(String(jobId || ""))) {
      resolve({ ok: false, code: "invalid_job_request" });
      return;
    }
    const request = http.request(`${BACKEND_URL}/api/jobs/${jobId}/${action}`, {
      method: "POST",
      timeout: action === "resume" ? 0 : 3000,
      headers: {
        "X-Data-Automation-Session": workerSessionSecret,
        "Content-Type": "application/json",
        "Content-Length": "2",
      },
    }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => {
        try { resolve(JSON.parse(body)); } catch { resolve({ ok: false, code: "worker_response_invalid" }); }
      });
    });
    request.once("error", () => resolve({ ok: false, code: "worker_request_failed" }));
    request.end("{}");
  });
}

function registerIpc() {
  const localIo = createLocalIo({
    existsSync: fs.existsSync,
    statSync: fs.statSync,
    showOpenDialog: (options) => dialog.showOpenDialog(options),
    openPath: (target) => shell.openPath(target),
  });
  const curlCache = createCurlCache({
    confirmOverwrite: async (kind) => {
      const label = kind === "wheat" ? "麦子拓展 cURL" : "柚子关键词 cURL";
      const result = await dialog.showMessageBox({
        type: "warning",
        buttons: ["取消", "覆盖"],
        defaultId: 0,
        cancelId: 0,
        title: "覆盖请求",
        message: `任务目录中已有${label}，确认覆盖吗？`,
      });
      return result.response === 1;
    },
  });

  ipcMain.handle("select-new-task-parent-directory", async () => {
    const result = await dialog.showOpenDialog({
      title: "选择新任务的保存位置",
      properties: ["openDirectory"],
    });
    return result.canceled || result.filePaths.length === 0 ? null : result.filePaths[0];
  });
  ipcMain.handle("select-task-directory", async () => {
    const result = await dialog.showOpenDialog({
      title: "选择已有任务",
      properties: ["openDirectory"],
    });
    return result.canceled || result.filePaths.length === 0 ? null : result.filePaths[0];
  });
  ipcMain.handle("open-asin-workbook", (_event, taskDir) => openOrSelectStep0Workbook(taskDir, {
    existsSync: fs.existsSync,
    openPath: (target) => shell.openPath(target),
    showOpenDialog: (options) => dialog.showOpenDialog(options),
  }));
  ipcMain.handle("select-input", (_event, kind, taskDir) => localIo.select(kind, taskDir));
  ipcMain.handle("open-output", (_event, kind, taskDir) => localIo.openOutput(kind, taskDir));
  ipcMain.handle("save-curl", async (_event, kind, taskDir, content) => {
    try { return await curlCache.save(kind, taskDir, content); }
    catch { return { ok: false, error: "curl_write_failed" }; }
  });
  ipcMain.handle("launch-debug-chrome", () => launchDebugChrome({
    env: process.env,
    existsSync: fs.existsSync,
    spawn,
    profileRoot: userPaths().chromeProfileRoot,
  }));
  ipcMain.handle("stop-job", (_event, jobId) => postJobAction("stop", jobId));
  ipcMain.handle("resume-job", (_event, jobId) => postJobAction("resume", jobId));
  ipcMain.handle("restart-job", (_event, jobId) => postJobAction("restart", jobId));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 680,
    title: "资料自动化工具",
    backgroundColor: "#f4f7fb",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  mainWindow.removeMenu();
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedExternalUrl(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!isAllowedInAppNavigation(mainWindow.webContents.getURL(), url)) event.preventDefault();
  });
  if (app.isPackaged || process.argv.includes("--built")) {
    mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  } else {
    mainWindow.loadURL(DEV_FRONTEND_URL);
  }
}

app.whenReady().then(async () => {
  registerIpc();
  if (!(await startBackend())) {
    dialog.showErrorBox("本地服务启动失败", "资料自动化工具 Worker 未能在 15 秒内启动。");
  }
  createWindow();
});

app.on("before-quit", () => { isQuitting = true; stopBackend(); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
