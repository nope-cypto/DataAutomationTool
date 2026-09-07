import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptsDir, "..");
const sourceRoot = path.resolve(frontendRoot, "..", "..");

function read(relativePath) {
  return fs.readFileSync(path.join(sourceRoot, relativePath), "utf8");
}

const app = read("web_workbench/frontend/src/App.tsx");
const workerApi = read("web_workbench/frontend/src/lib/workerApi.ts");
const electron = read("web_workbench/frontend/electron/main.cjs");
const preload = read("web_workbench/frontend/electron/preload.cjs");
const files = read("web_workbench/worker/files.py");

assert.match(app, />资料自动化工具</);
assert.match(app, /<StepHeading number="0" title="建立项目"/);
assert.match(app, />ASIN 输入表</);
for (const step of ["1", "2", "9"]) assert.match(app, new RegExp(`<StepCard number="${step}"`));
assert.doesNotMatch(app, /<StepCard number="3"/);

const runningStatusSection = app.match(/<section[^>]*aria-labelledby="running-status-title"[\s\S]*?<\/section>/)?.[0] || "";
const step0Section = app.match(/<section[^>]*aria-labelledby="step0-title"[\s\S]*?<\/section>/)?.[0] || "";
const step2Card = app.match(/<StepCard number="2"[\s\S]*?<\/StepCard>/)?.[0] || "";
assert.match(runningStatusSection, />任务运行状态</);
assert.match(runningStatusSection, /当前没有运行中或可继续的任务/);
assert.doesNotMatch(runningStatusSection, /StepHeading number="0"/);
assert.match(runningStatusSection, /role="list" aria-label="可操作任务" className="h-40 space-y-2 overflow-y-auto/);
assert.match(runningStatusSection, /role="listitem" className="flex h-12 items-center gap-3 whitespace-nowrap/);
assert.doesNotMatch(runningStatusSection, /overflow-x-auto|shrink-0/);
assert.match(step0Section, /StepHeading number="0" title="建立项目"/);
assert.match(step0Section, /step0Notice/);
assert.doesNotMatch(step0Section, /visibleJobs/);
assert.match(app, /const \[step0Expanded, setStep0Expanded\] = useState\(true\)/);
assert.match(step0Section, /aria-expanded=\{step0Expanded\}/);
assert.match(step0Section, /aria-controls="step0-content"/);
assert.match(step0Section, /\{step0Expanded && \(/);
assert.match(step0Section, /step0Expanded \? "收合" : "展开"/);
assert.doesNotMatch(app, /查看 ASIN 填写示例|showAsinExample|asin-input-example/);
assert.match(step2Card, /<Download className="h-4 w-4" \/>全量下载/);
assert.doesNotMatch(step2Card, /<Play className="h-4 w-4" \/>全量下载/);

assert.doesNotMatch(app, /step0-asin-example\.png/);
assert.equal(fs.existsSync(path.join(sourceRoot, "web_workbench/frontend/src/assets/step0-asin-example.png")), false);
assert.match(app, /selectNewTaskParentDirectory/);
assert.match(workerApi, /createTask = \(taskName: string, parentDir: string\)/);
assert.match(workerApi, /\{ taskName, parentDir \}/);
assert.match(preload, /selectNewTaskParentDirectory/);
assert.match(electron, /"select-new-task-parent-directory"/);

const newTaskHandler = electron.match(/ipcMain\.handle\("select-new-task-parent-directory"[\s\S]*?\n  \}\);/i)?.[0] || "";
assert.doesNotMatch(newTaskHandler, /defaultPath|mkdirSync/);

for (const folder of ["Step0_ASIN_Input", "Step1_Pomelo_Data", "Step2_Wheat_Expansion", "Step9_Pomelo_Keywords"]) {
  assert.match(files, new RegExp(folder));
}

assert.match(app, /柚子关键词下载/);
assert.doesNotMatch(app, /麦子关键词下载/);

for (const removedCopy of [
  "OPEN SOURCE",
  "LOCAL ONLY",
  "Keyword Crawler",
  "Crawler ",
  "打开目录",
  "西柚",
  "卖家精灵",
  "仅保留三个本地抓取器",
]) {
  assert.doesNotMatch(app, new RegExp(removedCopy, "i"));
}

console.log("User flow and naming checks passed.");
