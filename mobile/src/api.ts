import AsyncStorage from "@react-native-async-storage/async-storage";

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

interface TokenPair {
  access_token: string;
  refresh_token: string;
  device_id: string;
}

const KEYS = {
  server: "server_url",
  access: "access_token",
  refresh: "refresh_token",
  device: "device_id",
};

let cache: { server?: string; access?: string; refresh?: string; device?: string } = {};

export async function loadSession(): Promise<boolean> {
  const [server, access, refresh, device] = await Promise.all([
    AsyncStorage.getItem(KEYS.server),
    AsyncStorage.getItem(KEYS.access),
    AsyncStorage.getItem(KEYS.refresh),
    AsyncStorage.getItem(KEYS.device),
  ]);
  cache = {
    server: server ?? undefined,
    access: access ?? undefined,
    refresh: refresh ?? undefined,
    device: device ?? undefined,
  };
  return Boolean(server && access);
}

export function serverUrl(): string {
  if (!cache.server) throw new Error("Not connected to a server");
  return cache.server;
}

async function storeTokens(tokens: TokenPair): Promise<void> {
  cache.access = tokens.access_token;
  cache.refresh = tokens.refresh_token;
  cache.device = tokens.device_id;
  await AsyncStorage.multiSet([
    [KEYS.access, tokens.access_token],
    [KEYS.refresh, tokens.refresh_token],
    [KEYS.device, tokens.device_id],
  ]);
}

export async function logout(): Promise<void> {
  cache = { server: cache.server };
  await AsyncStorage.multiRemove([KEYS.access, KEYS.refresh, KEYS.device]);
}

export async function login(
  server: string,
  username: string,
  password: string,
): Promise<void> {
  const base = server.replace(/\/+$/, "");
  const response = await fetch(`${base}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, device_name: "android-app" }),
  });
  if (!response.ok) throw new Error("Login failed — check server URL and credentials");
  cache.server = base;
  await AsyncStorage.setItem(KEYS.server, base);
  await storeTokens(await response.json());
}

async function tryRefresh(): Promise<boolean> {
  if (!cache.refresh || !cache.device || !cache.server) return false;
  const response = await fetch(`${cache.server}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: cache.device, refresh_token: cache.refresh }),
  });
  if (!response.ok) return false;
  await storeTokens(await response.json());
  return true;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const go = () =>
    fetch(`${cache.server}/api${path}`, {
      ...init,
      headers: { ...(init.headers ?? {}), Authorization: `Bearer ${cache.access}` },
    });

  let response = await go();
  if (response.status === 401 && (await tryRefresh())) response = await go();
  return response;
}

export async function fetchAssets(offset: number, limit = 60): Promise<AssetPage> {
  const response = await apiFetch(`/assets?offset=${offset}&limit=${limit}`);
  if (!response.ok) throw new Error("Failed to load photos");
  return response.json();
}

export async function searchAssets(query: string): Promise<Asset[]> {
  const response = await apiFetch(`/search?q=${encodeURIComponent(query)}`);
  if (!response.ok) throw new Error("Search failed");
  return (await response.json()).items;
}

/** Signed URLs come back relative to the API root. */
export function fileUrl(signedPath: string): string {
  return `${cache.server}/api${signedPath}`;
}

export function accessToken(): string | undefined {
  return cache.access;
}
