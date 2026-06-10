const API = "/api";

export interface AssetUrls {
  grid: string | null;
  preview: string | null;
  original: string;
}

export interface Asset {
  id: string;
  media_type: string;
  width: number | null;
  height: number | null;
  size_bytes: number;
  taken_at: string | null;
  created_at: string;
  urls: AssetUrls;
}

export interface AssetPage {
  items: Asset[];
  total: number;
  offset: number;
  limit: number;
}

export interface Device {
  id: string;
  name: string;
  created_at: string;
  last_seen_at: string | null;
  revoked: boolean;
}

interface TokenPair {
  access_token: string;
  refresh_token: string;
  device_id: string;
}

const store = {
  get access() {
    return localStorage.getItem("access_token");
  },
  get refresh() {
    return localStorage.getItem("refresh_token");
  },
  get deviceId() {
    return localStorage.getItem("device_id");
  },
  set(tokens: TokenPair) {
    localStorage.setItem("access_token", tokens.access_token);
    localStorage.setItem("refresh_token", tokens.refresh_token);
    localStorage.setItem("device_id", tokens.device_id);
  },
  clear() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    localStorage.removeItem("device_id");
  },
};

export function isLoggedIn(): boolean {
  return store.access !== null;
}

export function logout(): void {
  store.clear();
}

export async function login(
  username: string,
  password: string,
): Promise<void> {
  const deviceName = `web-${navigator.platform || "browser"}`;
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, device_name: deviceName }),
  });
  if (!response.ok) throw new Error("Invalid username or password");
  store.set(await response.json());
}

async function tryRefresh(): Promise<boolean> {
  if (!store.refresh || !store.deviceId) return false;
  const response = await fetch(`${API}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      device_id: store.deviceId,
      refresh_token: store.refresh,
    }),
  });
  if (!response.ok) return false;
  store.set(await response.json());
  return true;
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const withAuth = (): RequestInit => ({
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${store.access}` },
  });

  let response = await fetch(`${API}${path}`, withAuth());
  if (response.status === 401 && (await tryRefresh())) {
    response = await fetch(`${API}${path}`, withAuth());
  }
  if (response.status === 401) {
    store.clear();
    window.location.reload();
  }
  return response;
}

export async function fetchAssets(offset: number, limit = 100): Promise<AssetPage> {
  const response = await apiFetch(`/assets?offset=${offset}&limit=${limit}`);
  if (!response.ok) throw new Error("Failed to load assets");
  return response.json();
}

export async function fetchDevices(): Promise<Device[]> {
  const response = await apiFetch("/devices");
  if (!response.ok) throw new Error("Failed to load devices");
  return response.json();
}

export async function revokeDevice(id: string): Promise<void> {
  const response = await apiFetch(`/devices/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error("Failed to revoke device");
}

/** Signed URLs come back relative to the API root. */
export function fileUrl(signedPath: string): string {
  return `${API}${signedPath}`;
}
