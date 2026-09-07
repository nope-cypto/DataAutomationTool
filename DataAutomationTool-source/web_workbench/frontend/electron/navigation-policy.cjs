function parseUrl(value) {
  try {
    return new URL(String(value));
  } catch {
    return null;
  }
}

function isAllowedExternalUrl(value) {
  const url = parseUrl(value);
  return Boolean(url && (url.protocol === "http:" || url.protocol === "https:"));
}

function isAllowedInAppNavigation(currentValue, targetValue) {
  const current = parseUrl(currentValue);
  const target = parseUrl(targetValue);
  if (!current || !target || current.protocol !== target.protocol) {
    return false;
  }
  if (current.protocol === "file:") {
    return current.pathname === target.pathname;
  }
  return current.origin === target.origin;
}

module.exports = {
  isAllowedExternalUrl,
  isAllowedInAppNavigation,
};
