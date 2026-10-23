import { useEffect, useState } from "react";

// "Saved for later" hearts. Stored only in this browser (never sent to the server), like recently viewed.
const KEY = "store_saved_products";
const EVENT = "store-saved-changed";

export function getSaved() {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v.filter(Number.isInteger) : []; }
  catch { return []; }
}

export function toggleSaved(id) {
  const now = getSaved();
  const next = now.includes(id) ? now.filter(x => x !== id) : [id, ...now].slice(0, 60);
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage blocked: the heart just will not persist */ }
  window.dispatchEvent(new Event(EVENT));
  return next.includes(id);
}

export function useSaved() {
  const [ids, setIds] = useState(getSaved);
  useEffect(() => {
    const sync = () => setIds(getSaved());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { window.removeEventListener(EVENT, sync); window.removeEventListener("storage", sync); };
  }, []);
  return ids;
}
