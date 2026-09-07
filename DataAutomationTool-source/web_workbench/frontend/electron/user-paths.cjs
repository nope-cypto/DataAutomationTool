const path = require("node:path");

function createUserPaths({ app }) {
  const userData = app.getPath("userData");
  return {
    chromeProfileRoot: path.join(userData, "chrome-debug-profile"),
  };
}

module.exports = { createUserPaths };
