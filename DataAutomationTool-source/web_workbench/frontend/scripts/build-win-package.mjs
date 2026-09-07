import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const sourceFrontendRoot = path.resolve(scriptsDir, "..");
const sourceWorkerRoot = path.resolve(sourceFrontendRoot, "..", "worker");
const excludedFrontendEntries = new Set(["node_modules", "dist", "release", ".build-logs"]);

function isDirectRun() {
  if (!process.argv[1]) return false;
  const currentFile = path.resolve(fileURLToPath(import.meta.url));
  const invokedFile = path.resolve(process.argv[1]);
  return process.platform === "win32"
    ? currentFile.toLowerCase() === invokedFile.toLowerCase()
    : currentFile === invokedFile;
}

function copyFrontendSource(frontendRoot, destination) {
  fs.cpSync(frontendRoot, destination, {
    recursive: true,
    filter(sourcePath) {
      const relativePath = path.relative(frontendRoot, sourcePath);
      if (!relativePath) return true;
      const [topLevelEntry] = relativePath.split(path.sep);
      return !excludedFrontendEntries.has(topLevelEntry);
    },
  });
}

export function stageBuildInputs({ frontendRoot, stageWebRoot }) {
  const stagedFrontend = path.join(stageWebRoot, "frontend");
  const stagedWorkerDist = path.join(stageWebRoot, "worker", "dist");
  fs.mkdirSync(stageWebRoot, { recursive: true });
  copyFrontendSource(frontendRoot, stagedFrontend);
  return { stagedFrontend, stagedWorkerDist };
}

export function createWorkerBuildEnvironment(baseEnvironment, stagedWorkerDist) {
  return {
    ...baseEnvironment,
    DATA_AUTOMATION_WORKER_DIST: stagedWorkerDist,
  };
}

function processIsRunning(processId) {
  if (!Number.isInteger(processId) || processId <= 0) return false;
  try {
    process.kill(processId, 0);
    return true;
  } catch (error) {
    return error?.code !== "ESRCH";
  }
}

export function acquireBuildLock(lockPath) {
  fs.mkdirSync(path.dirname(lockPath), { recursive: true });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const descriptor = fs.openSync(lockPath, "wx");
      fs.writeFileSync(descriptor, JSON.stringify({ processId: process.pid, startedAt: new Date().toISOString() }));
      let released = false;
      return {
        release() {
          if (released) return;
          released = true;
          fs.closeSync(descriptor);
          fs.rmSync(lockPath, { force: true });
        },
      };
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      let owner = null;
      try {
        owner = JSON.parse(fs.readFileSync(lockPath, "utf8"));
      } catch {
        // A malformed lock is stale and can be replaced.
      }
      if (owner && processIsRunning(Number(owner.processId))) {
        throw new Error(`Another Windows package build is already running (process ${owner.processId}). Stop it before starting a new build.`);
      }
      fs.rmSync(lockPath, { force: true });
    }
  }
  throw new Error("Unable to acquire the Windows package build lock.");
}

export function publishInstallerArtifacts({ stagedRelease, sourceRelease, onProgress = () => {} }) {
  if (!fs.existsSync(stagedRelease)) {
    throw new Error(`Electron installer output was not produced: ${stagedRelease}`);
  }
  const artifacts = fs
    .readdirSync(stagedRelease)
    .filter((name) => /^DataAutomationTool-Setup-.*-x64\.exe(?:\.blockmap)?$/.test(name))
    .sort();
  if (!artifacts.some((name) => name.endsWith(".exe"))) {
    throw new Error(`Electron installer executable was not produced: ${stagedRelease}`);
  }

  fs.mkdirSync(sourceRelease, { recursive: true });
  for (const artifact of artifacts) {
    const source = path.join(stagedRelease, artifact);
    const destination = path.join(sourceRelease, artifact);
    const temporary = path.join(sourceRelease, `.${artifact}.${process.pid}.publishing`);
    onProgress(`Publishing ${artifact}...`);
    try {
      fs.copyFileSync(source, temporary);
      fs.rmSync(destination, { force: true });
      fs.renameSync(temporary, destination);
    } finally {
      fs.rmSync(temporary, { force: true });
    }
  }

  return artifacts;
}

function createLogger(logPath) {
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  const stream = fs.createWriteStream(logPath, { flags: "a" });

  return {
    line(message = "") {
      const rendered = `${message}\n`;
      process.stdout.write(rendered);
      stream.write(rendered);
    },
    output(target, chunk) {
      target.write(chunk);
      stream.write(chunk);
    },
    close() {
      return new Promise((resolve, reject) => {
        stream.once("error", reject);
        stream.end(resolve);
      });
    },
  };
}

function runCommand(command, args, { cwd, env, label, logger }) {
  logger.line(`\n[${label}] ${command} ${args.join(" ")}`);

  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env,
      shell: false,
      windowsHide: false,
      stdio: ["inherit", "pipe", "pipe"],
    });

    child.stdout.on("data", (chunk) => logger.output(process.stdout, chunk));
    child.stderr.on("data", (chunk) => logger.output(process.stderr, chunk));
    child.once("error", (error) => {
      reject(new Error(`${label} could not start (${command}): ${error.message}`));
    });
    child.once("close", (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      const reason = signal ? `signal ${signal}` : `exit code ${code}`;
      reject(new Error(`${label} failed with ${reason}.`));
    });
  });
}

function localBuildRoot() {
  const configuredRoot = process.env.DATA_AUTOMATION_BUILD_ROOT?.trim();
  const baseRoot = configuredRoot
    ? path.resolve(configuredRoot)
    : path.join(process.env.LOCALAPPDATA || os.tmpdir(), "DataAutomationTool", "build");
  return path.join(baseRoot, "electron-stage");
}

function npmCliPath() {
  const candidates = [
    process.env.npm_execpath?.trim(),
    path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js"),
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error(`npm CLI was not found. Checked: ${candidates.join(", ")}`);
}

export function createNpmCommand(nodeExecutable, npmCli, args) {
  return {
    command: nodeExecutable,
    args: [npmCli, ...args],
  };
}

export function createBuildCommandDirectories({ frontendRoot, stagedFrontend }) {
  return {
    sourceTests: frontendRoot,
    npmInstall: stagedFrontend,
    frontendBuild: stagedFrontend,
    electronBuild: stagedFrontend,
  };
}

async function buildWindowsPackage() {
  if (process.platform !== "win32") {
    throw new Error("Windows installer packaging must be run on Windows.");
  }
  const nodeMajor = Number.parseInt(process.versions.node.split(".")[0], 10);
  if (!Number.isFinite(nodeMajor) || nodeMajor < 22) {
    throw new Error(`Node.js 22 or newer is required; current version is ${process.version}.`);
  }

  const timestamp = new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-");
  const logPath = path.join(sourceFrontendRoot, ".build-logs", `build-win-${timestamp}.log`);
  const buildRoot = localBuildRoot();
  const stageWebRoot = path.join(buildRoot, "web_workbench");
  const workerScript = path.join(sourceWorkerRoot, "build_worker.ps1");
  const npmCli = npmCliPath();
  const baseCommandEnv = {
    ...process.env,
    CSC_IDENTITY_AUTO_DISCOVERY: "false",
    npm_config_cache: path.join(buildRoot, "npm-cache"),
    npm_config_update_notifier: "false",
  };
  const buildLock = acquireBuildLock(path.join(path.dirname(buildRoot), "package-build.lock"));
  let logger = null;

  try {
    logger = createLogger(logPath);
    logger.line(`Windows package build started at ${new Date().toISOString()}`);
    logger.line(`Source: ${sourceFrontendRoot}`);
    logger.line(`Local staging: ${stageWebRoot}`);
    logger.line(`Node: ${process.version} (${process.arch})`);
    logger.line(`Complete log: ${logPath}`);

    logger.line("\n[Frontend staging] Preparing clean frontend sources in the local build directory...");
    logger.line(`[Frontend staging] Removing old local stage: ${buildRoot}`);
    fs.rmSync(buildRoot, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(stageWebRoot), { recursive: true });
    logger.line("[Frontend staging] Copying frontend source files (Worker binaries are not copied from SynologyDrive)...");
    const { stagedFrontend, stagedWorkerDist } = stageBuildInputs({
      frontendRoot: sourceFrontendRoot,
      stageWebRoot,
    });
    logger.line(`[Frontend staging] Frontend sources ready: ${stagedFrontend}`);

    const commandEnv = createWorkerBuildEnvironment(baseCommandEnv, stagedWorkerDist);
    logger.line(`[Worker build] Worker will be written directly to local staging: ${stagedWorkerDist}`);
    await runCommand(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", workerScript],
      { cwd: sourceFrontendRoot, env: commandEnv, label: "Worker build", logger },
    );
    const workerExecutable = path.join(stagedWorkerDist, "DataAutomationToolWorker.exe");
    if (!fs.existsSync(workerExecutable)) {
      throw new Error(`Worker executable was not produced: ${workerExecutable}`);
    }
    logger.line(`[Worker build] Local staged Worker ready: ${workerExecutable}`);

    fs.mkdirSync(commandEnv.npm_config_cache, { recursive: true });
    const commandDirectories = createBuildCommandDirectories({
      frontendRoot: sourceFrontendRoot,
      stagedFrontend,
    });

    const npmTest = createNpmCommand(process.execPath, npmCli, ["test"]);
    await runCommand(npmTest.command, npmTest.args, {
      cwd: commandDirectories.sourceTests,
      env: commandEnv,
      label: "Source boundary tests",
      logger,
    });
    const npmCi = createNpmCommand(process.execPath, npmCli, [
      "ci",
      "--foreground-scripts",
      "--no-audit",
      "--no-fund",
    ]);
    await runCommand(npmCi.command, npmCi.args, {
      cwd: commandDirectories.npmInstall,
      env: commandEnv,
      label: "npm ci",
      logger,
    });
    const npmBuild = createNpmCommand(process.execPath, npmCli, ["run", "build"]);
    await runCommand(npmBuild.command, npmBuild.args, {
      cwd: commandDirectories.frontendBuild,
      env: commandEnv,
      label: "Frontend build",
      logger,
    });
    const electronBuilder = createNpmCommand(process.execPath, npmCli, [
      "exec",
      "--",
      "electron-builder",
      "--win",
      "nsis",
      "--x64",
      "--publish",
      "never",
    ]);
    await runCommand(
      electronBuilder.command,
      electronBuilder.args,
      {
        cwd: commandDirectories.electronBuild,
        env: commandEnv,
        label: "Electron installer build",
        logger,
      },
    );

    const stagedRelease = path.join(stagedFrontend, "release");
    const sourceRelease = path.join(sourceFrontendRoot, "release");
    const artifacts = publishInstallerArtifacts({
      stagedRelease,
      sourceRelease,
      onProgress: (message) => logger.line(`[Installer publishing] ${message}`),
    });
    logger.line(`\nInstaller output: ${sourceRelease}`);
    for (const artifact of artifacts) logger.line(`- ${artifact}`);
    logger.line(`Build completed at ${new Date().toISOString()}`);
  } catch (error) {
    if (logger) {
      logger.line(`\nBUILD FAILED: ${error instanceof Error ? error.message : String(error)}`);
      logger.line(`Complete diagnostic log: ${logPath}`);
    }
    throw error;
  } finally {
    try {
      if (logger) await logger.close();
    } finally {
      buildLock.release();
    }
  }
}

if (isDirectRun()) {
  buildWindowsPackage().catch((error) => {
    process.stderr.write(`\n${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
