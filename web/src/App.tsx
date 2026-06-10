import { useState } from "react";
import { isLoggedIn, logout } from "./api";
import Devices from "./Devices";
import Gallery from "./Gallery";
import Login from "./Login";
import People from "./People";

type View = "gallery" | "people" | "devices";

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [view, setView] = useState<View>("gallery");

  if (!authed) return <Login onSuccess={() => setAuthed(true)} />;

  return (
    <>
      <header>
        <span className="brand">PhotoNest</span>
        <nav>
          <button
            className={view === "gallery" ? "active" : ""}
            onClick={() => setView("gallery")}
          >
            Photos
          </button>
          <button
            className={view === "people" ? "active" : ""}
            onClick={() => setView("people")}
          >
            People
          </button>
          <button
            className={view === "devices" ? "active" : ""}
            onClick={() => setView("devices")}
          >
            Devices
          </button>
          <button
            onClick={() => {
              logout();
              setAuthed(false);
            }}
          >
            Sign out
          </button>
        </nav>
      </header>
      <main>
        {view === "gallery" && <Gallery />}
        {view === "people" && <People />}
        {view === "devices" && <Devices />}
      </main>
    </>
  );
}
