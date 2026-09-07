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

function absent(relativePath) {
  assert.equal(fs.existsSync(path.join(sourceRoot, relativePath)), false, `${relativePath} should not exist`);
}

const api = read("web_workbench/worker/api.py");
const executor = read("web_workbench/worker/step_execution.py");
const app = read("web_workbench/frontend/src/App.tsx");
const electron = read("web_workbench/frontend/electron/main.cjs");
const seller = read("wheat_expansion/exporter.py");
const pomeloKeywords = read("pomelo_keywords_export.py");

for (const stepId of ["step1", "step2", "step9"]) {
  assert.match(api, new RegExp(`"id": "${stepId}"`));
}
for (const forbiddenStep of ["step1_2", "step1_3", "step2_1_2", "step2_1_4"]) {
  assert.doesNotMatch(api, new RegExp(`"id": "${forbiddenStep}"`));
}
for (const forbiddenAction of ["pomelo_generate_summary", "seller_merge", "feature_word", "top_asin_metrics"]) {
  assert.doesNotMatch(executor, new RegExp(forbiddenAction, "i"));
}
for (const forbiddenCloudMarker of ["supabase", "cloud_base_url", "vps_client"]) {
  assert.doesNotMatch(`${api}\n${executor}\n${app}\n${electron}`, new RegExp(forbiddenCloudMarker, "i"));
}
for (const exporter of [seller, pomeloKeywords]) {
  assert.doesNotMatch(exporter, /write_excel|to_excel|merged_json|merge_dedupe/i);
}

for (const removedModule of [
  "vps_client.py",
  "Step1_Pomelo_Data_summary.py",
  "Step2_Wheat_Expansion_merge_dedupe.py",
  "step1_2_aba_feature_word_report.py",
  "step2_1_4_top_asin_metrics.py",
  "feature_words.py",
  "web_workbench/worker/cloud.py",
  "web_workbench/worker/state_store.py",
]) {
  absent(removedModule);
}

console.log("Open-source automation boundary checks passed.");
