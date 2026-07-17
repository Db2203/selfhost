import { useCallback, useEffect, useState } from "react";
import {
  createAlbum,
  deleteAlbum,
  fetchAlbumAssets,
  fetchAlbums,
  fileUrl,
  removeFromAlbum,
  renameAlbum,
  type Album,
  type Asset,
} from "./api";
import { AssetTile, Lightbox } from "./Gallery";

function AlbumDetail({
  album,
  onBack,
  onChanged,
}: {
  album: Album;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<Asset | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAlbumAssets(album.id).then((list) => {
      if (!cancelled) setAssets(list);
    });
    return () => {
      cancelled = true;
    };
  }, [album.id]);

  async function rename() {
    const name = prompt("Album name:", album.name);
    if (!name?.trim()) return;
    await renameAlbum(album.id, name.trim());
    onChanged();
  }

  async function removeAlbum() {
    if (!confirm("Delete this album? The photos themselves are kept.")) return;
    await deleteAlbum(album.id);
    onChanged();
    onBack();
  }

  async function removeMember(asset: Asset) {
    await removeFromAlbum(album.id, asset.id);
    setAssets((prev) => prev.filter((a) => a.id !== asset.id));
    onChanged();
  }

  return (
    <div>
      <div className="person-toolbar">
        <button onClick={onBack}>← Albums</button>
        <h2>{album.name}</h2>
        <button onClick={rename}>Rename</button>
        <button onClick={removeAlbum}>Delete album</button>
      </div>
      {assets.length === 0 && (
        <p className="muted">
          Empty album — add photos from the gallery: open one and use “Add to album”.
        </p>
      )}
      <div className="grid">
        {assets.map((asset) => (
          <div key={asset.id} className="album-tile">
            <AssetTile asset={asset} onOpen={() => setSelected(asset)} />
            <button
              className="tile-remove"
              title="Remove from album"
              onClick={() => removeMember(asset)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      {selected && <Lightbox asset={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

export default function Albums() {
  const [albums, setAlbums] = useState<Album[]>([]);
  const [open, setOpen] = useState<Album | null>(null);

  const reload = useCallback(() => {
    fetchAlbums().then(setAlbums);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchAlbums().then((list) => {
      if (!cancelled) setAlbums(list);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function create() {
    const name = prompt("Name the new album:");
    if (!name?.trim()) return;
    const album = await createAlbum(name.trim());
    reload();
    setOpen(album);
  }

  if (open) {
    return <AlbumDetail album={open} onBack={() => setOpen(null)} onChanged={reload} />;
  }

  return (
    <>
      <div className="person-toolbar">
        <h2>Albums</h2>
        <button onClick={create}>New album</button>
      </div>
      {albums.length === 0 && (
        <div className="empty">
          <p>No albums yet.</p>
          <p className="muted">Create one, then add photos from the gallery.</p>
        </div>
      )}
      <div className="people-grid">
        {albums.map((album) => (
          <button key={album.id} className="person-card" onClick={() => setOpen(album)}>
            {album.cover ? (
              <img src={fileUrl(album.cover)} alt="" loading="lazy" />
            ) : (
              <div className="person-placeholder" />
            )}
            <span>{album.name}</span>
            <span className="muted">
              {album.asset_count} {album.asset_count === 1 ? "item" : "items"}
            </span>
          </button>
        ))}
      </div>
    </>
  );
}
