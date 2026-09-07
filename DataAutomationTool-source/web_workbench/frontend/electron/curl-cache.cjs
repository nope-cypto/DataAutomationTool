const fs = require("node:fs");
const path = require("node:path");

const TARGETS = {
  wheat: ["Step2_Wheat_Expansion", "Step2_Request.txt"],
  pomeloKeywords: ["Step9_Pomelo_Keywords", "Step9_Request.txt"],
};

function validateCurlText(content) {
  const normalized = String(content ?? "").trim();
  if (!normalized) return null;
  const firstToken = normalized.split(/\s+/, 1)[0].toLowerCase();
  return firstToken === "curl" || firstToken === "curl.exe" ? normalized : null;
}

function cachePath(kind, taskDir) {
  const target = TARGETS[kind];
  return target ? path.join(path.resolve(taskDir), ...target) : null;
}

function isInsideTaskDir(taskDir, candidate) {
  const root = path.resolve(taskDir) + path.sep;
  return candidate === path.resolve(taskDir) || candidate.startsWith(root);
}

function createCurlCache({
  existsSync = fs.existsSync,
  statSync = fs.statSync,
  readFileSync = fs.readFileSync,
  writeFileSync = fs.writeFileSync,
  confirmOverwrite,
}) {
  async function save(kind, taskDir, content) {
    if (!TARGETS[kind]) return { ok: false, error: "curl_kind_not_allowed" };
    if (typeof taskDir !== "string" || taskDir.trim() === "") return { ok: false, error: "task_dir_required" };
    const resolvedTask = path.resolve(taskDir);
    if (!existsSync(resolvedTask) || !statSync(resolvedTask).isDirectory()) return { ok: false, error: "task_dir_missing" };
    const target = cachePath(kind, resolvedTask);
    if (!isInsideTaskDir(resolvedTask, target)) return { ok: false, error: "curl_target_outside_task" };
    const normalized = validateCurlText(content);
    if (!normalized) return { ok: false, error: "curl_invalid" };
    if (existsSync(target) && readFileSync(target, "utf8").trim()) {
      const accepted = await confirmOverwrite(kind, target);
      if (!accepted) return { ok: false, cancelled: true };
    }
    writeFileSync(target, normalized, "utf8");
    return { ok: true };
  }

  return { save };
}

module.exports = { cachePath, createCurlCache, validateCurlText, isInsideTaskDir };
