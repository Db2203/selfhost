import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { fetchAssets, fileUrl, searchAssets, type Asset } from "./api";

export function Lightbox({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const src = asset.urls.preview ?? asset.urls.original;
  const taken = asset.taken_at
    ? new Date(asset.taken_at).toLocaleString()
    : "unknown date";

  return (
    <div className="lightbox" onClick={onClose}>
      <img src={fileUrl(src)} alt="" onClick={(e) => e.stopPropagation()} />
      <div className="lightbox-meta" onClick={(e) => e.stopPropagation()}>
        <span>{taken}</span>
        <span>
          {asset.width}×{asset.height} · {(asset.size_bytes / 1024 / 1024).toFixed(1)} MB
        </span>
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
  const loading = useRef(false);
  const sentinel = useRef<HTMLDivElement>(null);

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

  const shown = results ?? assets;

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
      </form>
      {results && (
        <p className="muted search-note">
          Top matches for “{query.trim()}”, best first
        </p>
      )}
      <div className="grid">
        {shown.map((asset) =>
          asset.urls.grid ? (
            <img
              key={asset.id}
              src={fileUrl(asset.urls.grid)}
              alt=""
              loading="lazy"
              onClick={() => setSelected(asset)}
            />
          ) : null,
        )}
      </div>
      {!results && <div ref={sentinel} className="sentinel" />}
      {selected && <Lightbox asset={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
