import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  deleteAsset,
  fetchAssets,
  fileUrl,
  searchAssets,
  setFavorite,
  type Asset,
} from "./api";

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "▶";
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function AssetTile({ asset, onOpen }: { asset: Asset; onOpen: () => void }) {
  if (!asset.urls.grid) return null;
  return (
    <div className="tile" onClick={onOpen}>
      <img src={fileUrl(asset.urls.grid)} alt="" loading="lazy" />
      {asset.media_type === "video" && (
        <span className="tile-duration">{formatDuration(asset.duration_seconds)}</span>
      )}
    </div>
  );
}

export function Lightbox({
  asset,
  onClose,
  onToggleFavorite,
  onDelete,
}: {
  asset: Asset;
  onClose: () => void;
  onToggleFavorite?: (asset: Asset) => void;
  onDelete?: (asset: Asset) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const taken = asset.taken_at
    ? new Date(asset.taken_at).toLocaleString()
    : "unknown date";

  return (
    <div className="lightbox" onClick={onClose}>
      {asset.media_type === "video" ? (
        <video
          src={fileUrl(asset.urls.playback ?? asset.urls.original)}
          poster={asset.urls.preview ? fileUrl(asset.urls.preview) : undefined}
          controls
          autoPlay
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <img
          src={fileUrl(asset.urls.preview ?? asset.urls.original)}
          alt=""
          onClick={(e) => e.stopPropagation()}
        />
      )}
      <div className="lightbox-meta" onClick={(e) => e.stopPropagation()}>
        <span>{taken}</span>
        <span>
          {asset.width}×{asset.height} · {(asset.size_bytes / 1024 / 1024).toFixed(1)} MB
          {asset.duration_seconds !== null && ` · ${formatDuration(asset.duration_seconds)}`}
        </span>
        {onToggleFavorite && (
          <button
            className={asset.favorite ? "favorite active" : "favorite"}
            title={asset.favorite ? "Remove from favorites" : "Add to favorites"}
            onClick={() => onToggleFavorite(asset)}
          >
            {asset.favorite ? "♥" : "♡"}
          </button>
        )}
        {onDelete && <button onClick={() => onDelete(asset)}>Delete</button>}
        <a href={fileUrl(asset.urls.original)} target="_blank" rel="noreferrer">
          Open original
        </a>
      </div>
    </div>
  );
}

export default function Gallery() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Asset[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [favorites, setFavorites] = useState<Asset[] | null>(null);
  const loading = useRef(false);
  const sentinel = useRef<HTMLDivElement>(null);

  /** Apply an updated asset to every list that may contain it. */
  function patchEverywhere(updated: Asset) {
    const patch = (list: Asset[]) => list.map((a) => (a.id === updated.id ? updated : a));
    setAssets(patch);
    setResults((prev) => (prev ? patch(prev) : prev));
    setFavorites((prev) =>
      prev ? patch(prev).filter((a) => a.favorite) : prev,
    );
    setSelected((prev) => (prev?.id === updated.id ? updated : prev));
  }

  async function toggleFavorite(asset: Asset) {
    patchEverywhere(await setFavorite(asset.id, !asset.favorite));
  }

  async function removeAsset(asset: Asset) {
    if (!confirm("Delete this item from your library?")) return;
    await deleteAsset(asset.id);
    const drop = (list: Asset[]) => list.filter((a) => a.id !== asset.id);
    setAssets((prev) => {
      const next = drop(prev);
      countRef.current = next.length;
      return next;
    });
    setResults((prev) => (prev ? drop(prev) : prev));
    setFavorites((prev) => (prev ? drop(prev) : prev));
    if (totalRef.current !== null) totalRef.current -= 1;
    setTotal((prev) => (prev === null ? prev : prev - 1));
    setSelected(null);
  }

  async function toggleFavoritesView() {
    if (favorites) {
      setFavorites(null);
      return;
    }
    setFavorites((await fetchAssets(0, 200, true)).items);
  }

  async function submitSearch(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      setResults((await searchAssets(query.trim())).items);
    } finally {
      setSearching(false);
    }
  }

  // Refs (not state) drive pagination so loadMore has a stable identity and
  // the IntersectionObserver isn't torn down/recreated on every page — which
  // would otherwise risk duplicate fetches of the same offset.
  const countRef = useRef(0);
  const totalRef = useRef<number | null>(null);

  const loadMore = useCallback(async () => {
    if (loading.current) return;
    if (totalRef.current !== null && countRef.current >= totalRef.current) return;
    loading.current = true;
    try {
      const page = await fetchAssets(countRef.current);
      setAssets((prev) => {
        const next = [...prev, ...page.items];
        countRef.current = next.length;
        return next;
      });
      totalRef.current = page.total;
      setTotal(page.total);
    } finally {
      loading.current = false;
    }
  }, []);

  useEffect(() => {
    const node = sentinel.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => entries[0].isIntersecting && loadMore(),
      { rootMargin: "600px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [loadMore]);

  if (total === 0) {
    return (
      <div className="empty">
        <p>No photos yet.</p>
        <p className="muted">
          Run <code>docker compose exec api python -m app.cli index &lt;user&gt;</code>{" "}
          to scan your library.
        </p>
      </div>
    );
  }

  const shown = results ?? favorites ?? assets;

  return (
    <>
      <form className="search" onSubmit={submitSearch}>
        <input
          placeholder='Search your photos, e.g. "sunset at the beach"'
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!e.target.value.trim()) setResults(null);
          }}
        />
        <button disabled={searching}>{searching ? "…" : "Search"}</button>
        {results && (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setResults(null);
            }}
          >
            Clear
          </button>
        )}
        <button
          type="button"
          className={favorites ? "active" : ""}
          title="Show favorites"
          onClick={toggleFavoritesView}
        >
          ♥
        </button>
      </form>
      {results && (
        <p className="muted search-note">
          Top matches for “{query.trim()}”, best first
        </p>
      )}
      {!results && favorites && (
        <p className="muted search-note">
          Favorites{favorites.length === 0 && " — none yet. Open a photo and tap ♡."}
        </p>
      )}
      <div className="grid">
        {shown.map((asset) => (
          <AssetTile key={asset.id} asset={asset} onOpen={() => setSelected(asset)} />
        ))}
      </div>
      {!results && !favorites && <div ref={sentinel} className="sentinel" />}
      {selected && (
        <Lightbox
          asset={selected}
          onClose={() => setSelected(null)}
          onToggleFavorite={toggleFavorite}
          onDelete={removeAsset}
        />
      )}
    </>
  );
}
