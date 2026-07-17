import { useCallback, useEffect, useState } from "react";
import {
  fetchPeople,
  fetchPersonAssets,
  fileUrl,
  mergePeople,
  renamePerson,
  type Asset,
  type Person,
} from "./api";
import { AssetTile, Lightbox } from "./Gallery";

function PersonDetail({
  person,
  others,
  onBack,
  onChanged,
}: {
  person: Person;
  others: Person[];
  onBack: () => void;
  onChanged: () => void;
}) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<Asset | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPersonAssets(person.id).then((list) => {
      if (!cancelled) setAssets(list);
    });
    return () => {
      cancelled = true;
    };
  }, [person.id]);

  async function rename() {
    const name = prompt("Name this person:", person.name ?? "");
    if (!name?.trim()) return;
    await renamePerson(person.id, name.trim());
    onChanged();
  }

  async function merge(otherId: string) {
    if (!otherId) return;
    if (!confirm("Merge the selected person into this one?")) return;
    await mergePeople(person.id, otherId);
    onChanged();
    onBack();
  }

  return (
    <div>
      <div className="person-toolbar">
        <button onClick={onBack}>← People</button>
        <h2>{person.name ?? "Unnamed"}</h2>
        <button onClick={rename}>Rename</button>
        {others.length > 0 && (
          <select defaultValue="" onChange={(e) => merge(e.target.value)}>
            <option value="" disabled>
              Merge another person into this one…
            </option>
            {others.map((other) => (
              <option key={other.id} value={other.id}>
                {other.name ?? "Unnamed"} ({other.face_count})
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="grid">
        {assets.map((asset) => (
          <AssetTile key={asset.id} asset={asset} onOpen={() => setSelected(asset)} />
        ))}
      </div>
      {selected && <Lightbox asset={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

export default function People() {
  const [people, setPeople] = useState<Person[]>([]);
  const [open, setOpen] = useState<Person | null>(null);

  const reload = useCallback(() => {
    fetchPeople().then(setPeople);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchPeople().then((list) => {
      if (!cancelled) setPeople(list);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (open) {
    return (
      <PersonDetail
        person={open}
        others={people.filter((p) => p.id !== open.id)}
        onBack={() => setOpen(null)}
        onChanged={reload}
      />
    );
  }

  if (people.length === 0) {
    return (
      <div className="empty">
        <p>No people yet.</p>
        <p className="muted">
          Faces are grouped automatically after your library is indexed.
        </p>
      </div>
    );
  }

  return (
    <div className="people-grid">
      {people.map((person) => (
        <button key={person.id} className="person-card" onClick={() => setOpen(person)}>
          {person.cover ? (
            <img src={fileUrl(person.cover)} alt="" loading="lazy" />
          ) : (
            <div className="person-placeholder" />
          )}
          <span>{person.name ?? "Add name"}</span>
          <span className="muted">{person.face_count} photos</span>
        </button>
      ))}
    </div>
  );
}
