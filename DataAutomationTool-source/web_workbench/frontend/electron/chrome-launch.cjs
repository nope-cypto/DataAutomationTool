const path = require("node:path");
const http = require("node:http");
const fs = require("node:fs");

function probeDebugEndpoint() {
  return new Promise((resolve) => {
    const request = http.get({
      host: "127.0.0.1",
      port: 9222,
      path: "/json/version",
      timeout: 1000,
    }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        if (body.length < 16_384) body += chunk;
      });
      response.on("end", () => {
        try {
          const payload = JSON.parse(body);
          resolve(response.statusCode === 200 && validDebuggerUrl(payload?.webSocketDebuggerUrl));
        } catch {
          resolve(false);
        }
      });
    });
    request.on("timeout", () => request.destroy());
    request.on("error", () => resolve(false));
  });
}

function validDebuggerUrl(value) {
  return typeof value === "string" && /^wss?:\/\/(?:127\.0\.0\.1|localhost):9222\//i.test(value);
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function candidateChromePaths(env) {
  return [
    env.ProgramFiles,
    env["ProgramFiles(x86)"],
    env.LOCALAPPDATA,
  ].filter(Boolean).map((base) => path.join(base, "Google", "Chrome", "Application", "chrome.exe"));
}

async function launchDebugChrome({
  env,
  existsSync,
  spawn,
  profileRoot,
  mkdirSync = fs.mkdirSync,
  probeCdp = probeDebugEndpoint,
  wait: waitForNextProbe = wait,
  readinessAttempts = 20,
}) {
  const executable = candidateChromePaths(env).find((candidate) => existsSync(candidate));
  if (!executable) {
    return { ok: false, error: "chrome_not_found" };
  }

  const args = [
    "--remote-debugging-port=9222",
    `--user-data-dir=${profileRoot}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--new-window",
    "https://www.xydc.com/asin",
  ];
  try {
    mkdirSync(profileRoot, { recursive: true });
    const child = spawn(executable, args, { detached: true, windowsHide: false, stdio: "ignore" });
    child.unref();
  } catch {
    return { ok: false, error: "chrome_launch_failed" };
  }

  for (let attempt = 0; attempt < readinessAttempts; attempt += 1) {
    try {
      if (await probeCdp()) return { ok: true };
    } catch {
      // A failed probe is equivalent to CDP not being ready yet.
    }
    if (attempt + 1 < readinessAttempts) await waitForNextProbe(250);
  }
  return { ok: false, error: "chrome_cdp_not_ready" };
}

module.exports = { candidateChromePaths, launchDebugChrome, probeDebugEndpoint, validDebuggerUrl };
