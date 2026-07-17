const API = "/api";

export interface AssetUrls {
  grid: string | null;
  preview: string | null;
  original: string;
  /** Videos only: stream the browser can always play. */
  playback: string | null;
}

export interface Asset {
  id: string;
  media_type: string;
  width: number | null;
  height: number | null;
  size_bytes: number;
  taken_at: string | null;
  created_at: string;
  duration_seconds: number | null;
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

async function doRefresh(): Promise<boolean> {
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

// Refresh tokens are single-use (rotated server-side). If several requests
// 401 at once they must NOT each refresh — the first would invalidate the
// token the others present. Coalesce concurrent refreshes onto one promise.
let refreshInFlight: Promise<boolean> | null = null;

function tryRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
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

export interface SearchResults {
  query: string;
  items: Asset[];
}

export async function searchAssets(query: string): Promise<SearchResults> {
  const response = await apiFetch(`/search?q=${encodeURIComponent(query)}`);
  if (!response.ok) throw new Error("Search failed");
  return response.json();
}

export interface Person {
  id: string;
  name: string | null;
  face_count: number;
  cover: string | null;
}

export async function fetchPeople(): Promise<Person[]> {
  const response = await apiFetch("/people");
  if (!response.ok) throw new Error("Failed to load people");
  return response.json();
}

export async function renamePerson(id: string, name: string): Promise<void> {
  const response = await apiFetch(`/people/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) throw new Error("Rename failed");
}

export async function mergePeople(targetId: string, otherId: string): Promise<void> {
  const response = await apiFetch(`/people/${targetId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ other_id: otherId }),
  });
  if (!response.ok) throw new Error("Merge failed");
}

export async function fetchPersonAssets(id: string): Promise<Asset[]> {
  const response = await apiFetch(`/people/${id}/assets`);
  if (!response.ok) throw new Error("Failed to load person's photos");
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
