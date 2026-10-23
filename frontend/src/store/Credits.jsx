import { useEffect, useState } from "react";
import { ErrorState, Loading } from "../components/ui";

/** Photos are freely licensed images from Wikimedia Commons; the licence and author of each is listed here. */
export default function Credits() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { fetch("/products/credits.json").then(r => r.json()).then(setData).catch(() => setError("Could not load the image credits.")); }, []);
  if (error) return <ErrorState error={error}/>;
  if (!data) return <Loading text="Loading credits…"/>;
  return <div><h1>Image credits</h1>
    <p className="muted-text">Generic product photos are openly licensed images from Wikimedia Commons. Each remains under its own licence. Products without a photo here show a category illustration. Replace them with your own photography for a real deployment.</p>
    <table><thead><tr><th scope="col">Image file</th><th scope="col">Photo</th><th scope="col">Author</th><th scope="col">Licence</th></tr></thead>
      <tbody>{Object.entries(data).sort().map(([sku, c]) => <tr key={sku}><td>{sku}</td>
        <td><a href={c.page} target="_blank" rel="noopener noreferrer">{c.title.replace(/^File:/, "")}</a></td><td>{c.author}</td><td>{c.license}</td></tr>)}</tbody></table></div>;
}
