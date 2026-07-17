import AsyncStorage from "@react-native-async-storage/async-storage";
import * as MediaLibrary from "expo-media-library/legacy";
import { useEffect, useState } from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { accessToken, serverUrl } from "./api";
import { colors } from "./theme";

const UPLOADED_KEY = "uploaded_asset_ids";
const BATCH = 50;

async function loadUploaded(): Promise<Set<string>> {
  const raw = await AsyncStorage.getItem(UPLOADED_KEY);
  return new Set(raw ? (JSON.parse(raw) as string[]) : []);
}

async function saveUploaded(ids: Set<string>): Promise<void> {
  await AsyncStorage.setItem(UPLOADED_KEY, JSON.stringify([...ids]));
}

const MIME_BY_EXT: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  gif: "image/gif",
  webp: "image/webp",
  heic: "image/heic", // iPhone default format; the server handles it
  heif: "image/heif",
  mp4: "video/mp4",
  mov: "video/quicktime", // iPhone videos; the server transcodes HEVC
  m4v: "video/x-m4v",
};

const MEDIA_TYPES: MediaLibrary.MediaTypeValue[] = ["photo", "video"];

async function uploadPhoto(asset: MediaLibrary.Asset): Promise<void> {
  const info = await MediaLibrary.getAssetInfoAsync(asset);
  const uri = info.localUri ?? asset.uri;
  const fallbackExt = asset.mediaType === "video" ? "mp4" : "jpg";
  const name = asset.filename || `${asset.id}.${fallbackExt}`;
  const ext = name.split(".").pop()?.toLowerCase() ?? fallbackExt;

  const form = new FormData();
  // React Native's FormData accepts {uri, name, type} file descriptors.
  form.append("file", {
    uri,
    name,
    type: MIME_BY_EXT[ext] ?? "image/jpeg",
  } as unknown as Blob);

  const response = await fetch(`${serverUrl()}/api/assets/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken()}` },
    body: form,
  });
  if (!response.ok) throw new Error(`Upload failed (${response.status})`);
}

export default function BackupScreen() {
  const [permission, setPermission] = useState<boolean | null>(null);
  const [totalOnDevice, setTotalOnDevice] = useState(0);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const result = await MediaLibrary.requestPermissionsAsync();
      if (cancelled) return;
      setPermission(result.granted);
      if (result.granted) {
        const page = await MediaLibrary.getAssetsAsync({
          mediaType: MEDIA_TYPES,
          first: 1,
        });
        const uploaded = await loadUploaded();
        if (!cancelled) {
          setTotalOnDevice(page.totalCount);
          setUploadedCount(uploaded.size);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function backUpNow() {
    setRunning(true);
    setStatus(null);
    try {
      const uploaded = await loadUploaded();
      let cursor: string | undefined;
      let sent = 0;
      let failed = 0;

      for (;;) {
        const page = await MediaLibrary.getAssetsAsync({
          mediaType: MEDIA_TYPES,
          first: BATCH,
          after: cursor,
          sortBy: MediaLibrary.SortBy.creationTime,
        });
        for (const asset of page.assets) {
          if (uploaded.has(asset.id)) continue;
          try {
            await uploadPhoto(asset);
            uploaded.add(asset.id);
            sent += 1;
            if (sent % 10 === 0) {
              await saveUploaded(uploaded);
              setUploadedCount(uploaded.size);
              setStatus(`Uploading… ${sent} sent`);
            }
          } catch {
            failed += 1;
          }
        }
        if (!page.hasNextPage) break;
        cursor = page.endCursor;
      }

      await saveUploaded(uploaded);
      setUploadedCount(uploaded.size);
      setStatus(
        failed
          ? `Done: ${sent} uploaded, ${failed} failed (will retry next run)`
          : `Done: ${sent} uploaded`,
      );
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Backup failed");
    } finally {
      setRunning(false);
    }
  }

  if (permission === false) {
    return (
      <View style={styles.wrap}>
        <Text style={styles.text}>
          Photo-library permission is required to back up your camera roll.
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>Camera-roll backup</Text>
      <Text style={styles.text}>
        {uploadedCount} of {totalOnDevice} photos & videos backed up to your server.
      </Text>
      <Text style={styles.muted}>
        Everything is deduplicated by content on the server, so re-running is
        always safe.
      </Text>
      <TouchableOpacity style={styles.button} disabled={running} onPress={backUpNow}>
        <Text style={styles.buttonText}>{running ? "Backing up…" : "Back up now"}</Text>
      </TouchableOpacity>
      {status && <Text style={styles.text}>{status}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.bg, padding: 24, gap: 14 },
  title: { color: colors.text, fontSize: 20, fontWeight: "600" },
  text: { color: colors.text },
  muted: { color: colors.muted },
  button: {
    backgroundColor: colors.surface,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 8,
    alignItems: "center",
    paddingVertical: 14,
    marginTop: 10,
  },
  buttonText: { color: colors.accent, fontWeight: "600" },
});
