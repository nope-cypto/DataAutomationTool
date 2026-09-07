import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createUserPaths } = require("../electron/user-paths.cjs");

const fixtureRoot = path.resolve("runtime-path-test-user");
const redirectedDocuments = path.join(fixtureRoot, "OneDrive", "Documents");
const localAppData = path.join(fixtureRoot, "AppData", "Local");
const userData = path.join(fixtureRoot, "AppData", "Roaming", "Data Automation Tool");
assert.equal(path.isAbsolute(fixtureRoot), true);
const app = {
  getPath(name) {
    if (name === "documents") return redirectedDocuments;
    if (name === "userData") return userData;
    throw new Error(`Unexpected Electron path: ${name}`);
  },
};

const localPaths = createUserPaths({ app, env: { LOCALAPPDATA: localAppData } });
assert.equal("taskRoot" in localPaths, false, "new tasks must not receive a preset directory");
assert.equal(localPaths.chromeProfileRoot, path.join(userData, "chrome-debug-profile"));

console.log("Packaged runtime path checks passed.");
