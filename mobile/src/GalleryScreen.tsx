import { useVideoPlayer, VideoView } from "expo-video";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Dimensions,
  FlatList,
  Image,
  Modal,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { fetchAssets, fileUrl, searchAssets, type Asset } from "./api";
import { colors } from "./theme";

const COLUMNS = 3;
const tile = Dimensions.get("window").width / COLUMNS;

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "▶";
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function Lightbox({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  const src = asset.urls.preview ?? asset.urls.original;
  const taken = asset.taken_at ? new Date(asset.taken_at).toLocaleString() : "unknown date";
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <TouchableOpacity style={styles.lightbox} activeOpacity={1} onPress={onClose}>
        <Image source={{ uri: fileUrl(src) }} style={styles.lightboxImage} resizeMode="contain" />
        <Text style={styles.meta}>
          {taken} · {asset.width}×{asset.height}
        </Text>
      </TouchableOpacity>
    </Modal>
  );
}

function VideoLightbox({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  const player = useVideoPlayer(fileUrl(asset.urls.playback ?? asset.urls.original), (p) => {
    p.play();
  });
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.lightbox}>
        <VideoView
          player={player}
          style={styles.lightboxImage}
          contentFit="contain"
          nativeControls
        />
        <TouchableOpacity onPress={onClose}>
          <Text style={styles.meta}>Close</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );
}

export default function GalleryScreen() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Asset[] | null>(null);
  const loading = useRef(false);

  const loadMore = useCallback(async () => {
    if (loading.current) return;
    if (total !== null && assets.length >= total) return;
    loading.current = true;
    try {
      const page = await fetchAssets(assets.length);
      setAssets((prev) => [...prev, ...page.items]);
      setTotal(page.total);
    } finally {
      loading.current = false;
    }
  }, [assets.length, total]);

  useEffect(() => {
    void loadMore();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submitSearch() {
    const q = query.trim();
    if (!q) {
      setResults(null);
      return;
    }
    setResults(await searchAssets(q));
  }

  const shown = results ?? assets;

  return (
    <View style={styles.wrap}>
      <View style={styles.searchRow}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search, e.g. “sunset at the beach”"
          placeholderTextColor={colors.muted}
          value={query}
          onChangeText={(value) => {
            setQuery(value);
            if (!value.trim()) setResults(null);
          }}
          onSubmitEditing={submitSearch}
          returnKeyType="search"
        />
      </View>
      <FlatList
        data={shown}
        numColumns={COLUMNS}
        keyExtractor={(item) => item.id}
        onEndReached={results ? undefined : loadMore}
        onEndReachedThreshold={2}
        renderItem={({ item }) =>
          item.urls.grid ? (
            <TouchableOpacity onPress={() => setSelected(item)}>
              <Image source={{ uri: fileUrl(item.urls.grid) }} style={styles.tile} />
              {item.media_type === "video" && (
                <Text style={styles.tileDuration}>{formatDuration(item.duration_seconds)}</Text>
              )}
            </TouchableOpacity>
          ) : null
        }
        ListEmptyComponent={
          total === 0 ? (
            <Text style={styles.empty}>No photos yet — index your library on the server.</Text>
          ) : null
        }
      />
      {selected &&
        (selected.media_type === "video" ? (
          <VideoLightbox asset={selected} onClose={() => setSelected(null)} />
        ) : (
          <Lightbox asset={selected} onClose={() => setSelected(null)} />
        ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.bg },
  searchRow: { padding: 8 },
  searchInput: {
    backgroundColor: colors.surface,
    color: colors.text,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  tile: { width: tile, height: tile, backgroundColor: colors.surface },
  tileDuration: {
    position: "absolute",
    right: 6,
    bottom: 6,
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 4,
    overflow: "hidden",
    backgroundColor: "rgba(0,0,0,0.65)",
    color: "#fff",
    fontSize: 11,
  },
  empty: { color: colors.muted, textAlign: "center", marginTop: 60, padding: 20 },
  lightbox: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.95)",
    alignItems: "center",
    justifyContent: "center",
  },
  lightboxImage: { width: "100%", height: "85%" },
  meta: { color: colors.muted, marginTop: 10 },
});
