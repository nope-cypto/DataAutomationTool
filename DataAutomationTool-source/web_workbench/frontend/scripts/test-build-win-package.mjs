import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  acquireBuildLock,
  createBuildCommandDirectories,
  createNpmCommand,
  createWorkerBuildEnvironment,
  publishInstallerArtifacts,
  stageBuildInputs,
} from "./build-win-package.mjs";

const scratchRoot = fs.mkdtempSync(path.join(os.tmpdir(), "data-automation-tool-stage-test-"));

try {
  const sourceWebRoot = path.join(scratchRoot, "source", "web_workbench");
  const frontendRoot = path.join(sourceWebRoot, "frontend");
  const stageWebRoot = path.join(scratchRoot, "stage", "web_workbench");

  for (const relativePath of [
    "frontend/src/App.tsx",
    "frontend/scripts/check.mjs",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/node_modules/native-addon.node",
    "frontend/dist/index.html",
    "frontend/release/old-installer.exe",
    "frontend/.build-logs/old.log",
    "worker/dist/DataAutomationToolWorker.exe",
  ]) {
    const target = path.join(sourceWebRoot, relativePath);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, relativePath);
  }

  const { stagedFrontend, stagedWorkerDist } = stageBuildInputs({ frontendRoot, stageWebRoot });

  assert.equal(stagedFrontend, path.join(stageWebRoot, "frontend"));
  assert.equal(stagedWorkerDist, path.join(stageWebRoot, "worker", "dist"));
  for (const included of [
    "src/App.tsx",
    "scripts/check.mjs",
    "package.json",
    "package-lock.json",
  ]) {
    assert.equal(fs.existsSync(path.join(stagedFrontend, included)), true, `${included} should be staged`);
  }
  assert.equal(
    fs.existsSync(path.join(stageWebRoot, "worker", "dist", "DataAutomationToolWorker.exe")),
    false,
    "staging must not copy the large Worker package back from the synchronized source folder",
  );
  for (const excluded of ["node_modules", "dist", "release", ".build-logs"]) {
    assert.equal(fs.existsSync(path.join(stagedFrontend, excluded)), false, `${excluded} should not be staged`);
  }

  const npmCommand = createNpmCommand(
    "C:\\Program Files\\nodejs\\node.exe",
    "C:\\Program Files\\nodejs\\node_modules\\npm\\bin\\npm-cli.js",
    ["ci", "--foreground-scripts", "--no-audit", "--no-fund"],
  );
  assert.equal(npmCommand.command, "C:\\Program Files\\nodejs\\node.exe");
  assert.deepEqual(npmCommand.args, [
    "C:\\Program Files\\nodejs\\node_modules\\npm\\bin\\npm-cli.js",
    "ci",
    "--foreground-scripts",
    "--no-audit",
    "--no-fund",
  ]);

  assert.deepEqual(
    createBuildCommandDirectories({ frontendRoot, stagedFrontend }),
    {
      sourceTests: frontendRoot,
      npmInstall: stagedFrontend,
      frontendBuild: stagedFrontend,
      electronBuild: stagedFrontend,
    },
  );

  assert.deepEqual(
    createWorkerBuildEnvironment({ EXISTING_SETTING: "kept" }, stagedWorkerDist),
    {
      EXISTING_SETTING: "kept",
      DATA_AUTOMATION_WORKER_DIST: stagedWorkerDist,
    },
  );

  const workerBuildScript = fs.readFileSync(
    path.resolve(import.meta.dirname, "..", "..", "worker", "build_worker.ps1"),
    "utf8",
  );
  assert.match(
    workerBuildScript,
    /\$env:DATA_AUTOMATION_WORKER_DIST/,
    "the Worker build must support writing directly into the local Electron staging directory",
  );

  const stagedRelease = path.join(scratchRoot, "local-stage", "release");
  const sourceRelease = path.join(scratchRoot, "synchronized-source", "release");
  fs.mkdirSync(stagedRelease, { recursive: true });
  fs.mkdirSync(sourceRelease, { recursive: true });
  fs.writeFileSync(path.join(stagedRelease, "DataAutomationTool-Setup-1.1.5-x64.exe"), "new-installer");
  fs.writeFileSync(path.join(stagedRelease, "DataAutomationTool-Setup-1.1.5-x64.exe.blockmap"), "new-blockmap");
  fs.writeFileSync(path.join(stagedRelease, "builder-debug.yml"), "ignored");
  fs.writeFileSync(path.join(sourceRelease, "DataAutomationTool-Setup-1.1.4-x64.exe"), "old-installer");
  fs.writeFileSync(path.join(sourceRelease, "keep-me.txt"), "keep");

  const published = publishInstallerArtifacts({ stagedRelease, sourceRelease });

  assert.deepEqual(published, [
    "DataAutomationTool-Setup-1.1.5-x64.exe",
    "DataAutomationTool-Setup-1.1.5-x64.exe.blockmap",
  ]);
  assert.equal(fs.readFileSync(path.join(sourceRelease, published[0]), "utf8"), "new-installer");
  assert.equal(fs.existsSync(path.join(sourceRelease, "keep-me.txt")), true, "publishing must not delete the release directory");
  assert.equal(
    fs.existsSync(path.join(sourceRelease, "DataAutomationTool-Setup-1.1.4-x64.exe")),
    true,
    "publishing a new installer must not risk the build by deleting an older artifact",
  );

  const lockPath = path.join(scratchRoot, "package-build.lock");
  const buildLock = acquireBuildLock(lockPath);
  assert.throws(() => acquireBuildLock(lockPath), /another Windows package build is already running/i);
  buildLock.release();
  acquireBuildLock(lockPath).release();
} finally {
  fs.rmSync(scratchRoot, { recursive: true, force: true });
}

console.log("Windows packaging stage checks passed.");
