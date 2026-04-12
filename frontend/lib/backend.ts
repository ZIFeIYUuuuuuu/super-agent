const DEFAULT_BACKEND_URL = "http://127.0.0.1:8010";

function normalizeBaseUrl(value: string) {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

export function getBackendBaseUrl() {
  return normalizeBaseUrl(process.env.BACKEND_URL || DEFAULT_BACKEND_URL);
}

export function buildBackendUrl(path: string) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getBackendBaseUrl()}${normalizedPath}`;
}
