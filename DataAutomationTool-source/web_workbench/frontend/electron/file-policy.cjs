const path = require("node:path");

const TRANSIENT_SUFFIXES = [".tmp", ".part", ".crdownload"];

function isTransientWorkflowFile(candidate) {
  const name = path.basename(String(candidate || "")).toLowerCase();
  return name.startsWith("~$")
    || name.startsWith(".")
    || TRANSIENT_SUFFIXES.some((suffix) => name.endsWith(suffix) || name.includes(`${suffix}.`));
}

module.exports = { isTransientWorkflowFile };
