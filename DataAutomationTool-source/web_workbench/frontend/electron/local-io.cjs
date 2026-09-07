const path = require("node:path");
const { isTransientWorkflowFile } = require("./file-policy.cjs");

const OUTPUT_DIRS = {
  pomelo: "Step1_Pomelo_Data",
  wheat: "Step2_Wheat_Expansion",
  pomeloKeywords: "Step9_Pomelo_Keywords",
};

function taskDirectoryError(taskDir, { existsSync, statSync }) {
  if (typeof taskDir !== "string" || taskDir.trim() === "") return "task_dir_required";
  const resolved = path.resolve(taskDir);
  if (!existsSync(resolved) || !statSync(resolved).isDirectory()) return "task_dir_missing";
  return null;
}

function createLocalIo({ existsSync, statSync, showOpenDialog, openPath }) {
  const lastDirectories = new Map();

  async function select(kind, taskDir) {
    const error = taskDirectoryError(taskDir, { existsSync, statSync });
    if (error) return { ok: false, error, paths: [] };
    const definitions = {
      pomelo: {
        title: "选择柚子数据任务档案",
        defaultPath: path.join(taskDir, "Step0_ASIN_Input", "Step0_ASIN_Input.xlsx"),
        filters: [{ name: "CSV/Excel", extensions: ["csv", "xlsx", "xlsm"] }],
      },
      pomeloKeywords: {
        title: "选择柚子关键词档案",
        defaultPath: taskDir,
        filters: [{ name: "关键词文件", extensions: ["txt", "csv", "xlsx", "xlsm"] }],
      },
    };
    const definition = definitions[kind];
    if (!definition) return { ok: false, error: "local_action_not_allowed", paths: [] };
    const result = await showOpenDialog({
      title: definition.title,
      defaultPath: lastDirectories.get(kind) || definition.defaultPath,
      properties: ["openFile"],
      filters: definition.filters,
    });
    if (result.canceled || result.filePaths.length === 0) return { ok: false, cancelled: true, paths: [] };
    if (isTransientWorkflowFile(result.filePaths[0])) return { ok: false, error: "temporary_input_not_allowed", paths: [] };
    lastDirectories.set(kind, path.dirname(result.filePaths[0]));
    return { ok: true, paths: result.filePaths };
  }

  async function openOutput(kind, taskDir) {
    const error = taskDirectoryError(taskDir, { existsSync, statSync });
    if (error) return { ok: false, error };
    const dirname = OUTPUT_DIRS[kind];
    if (!dirname) return { ok: false, error: "local_action_not_allowed" };
    const target = path.join(path.resolve(taskDir), dirname);
    if (!existsSync(target) || !statSync(target).isDirectory()) return { ok: false, error: "directory_missing" };
    const openError = await openPath(target);
    return openError ? { ok: false, error: "directory_open_failed" } : { ok: true, path: target };
  }

  return { select, openOutput };
}

module.exports = { createLocalIo };
