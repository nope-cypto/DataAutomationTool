const path = require("node:path");
const { isTransientWorkflowFile } = require("./file-policy.cjs");

const STEP0_DIRECTORY = "Step0_ASIN_Input";
const STEP0_WORKBOOK = "Step0_ASIN_Input.xlsx";
const EXCEL_SUFFIXES = new Set([".xlsx", ".xlsm"]);

function step0WorkbookPath(taskDir) {
  return path.resolve(taskDir, STEP0_DIRECTORY, STEP0_WORKBOOK);
}

async function openOrSelectStep0Workbook(taskDir, { existsSync, openPath, showOpenDialog }) {
  if (typeof taskDir !== "string" || taskDir.trim() === "") {
    return { ok: false, error: "task_dir_required" };
  }

  const fixedWorkbook = step0WorkbookPath(taskDir);
  let target = fixedWorkbook;
  if (!existsSync(fixedWorkbook)) {
    const result = await showOpenDialog({
      title: "选择 Step 0 ASIN 输入表",
      defaultPath: path.dirname(fixedWorkbook),
      properties: ["openFile"],
      filters: [{ name: "Excel", extensions: ["xlsx", "xlsm"] }],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { ok: false, cancelled: true };
    }
    target = result.filePaths[0];
  }

  if (isTransientWorkflowFile(target) || !EXCEL_SUFFIXES.has(path.extname(target).toLowerCase())) {
    return { ok: false, error: "step0_workbook_type_invalid" };
  }

  try {
    const openError = await openPath(target);
    return openError
      ? { ok: false, error: "step0_workbook_open_failed" }
      : { ok: true };
  } catch {
    return { ok: false, error: "step0_workbook_open_failed" };
  }
}

module.exports = {
  openOrSelectStep0Workbook,
  step0WorkbookPath,
};
