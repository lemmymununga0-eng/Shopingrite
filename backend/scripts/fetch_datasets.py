r"""Download the public datasets recommended for this system, safely and with a record of where each came from.

    python scripts/fetch_datasets.py list
    python scripts/fetch_datasets.py info phiusiil
    python scripts/fetch_datasets.py get phiusiil --accept-licence
    python scripts/fetch_datasets.py get paysim --accept-licence            (needs your Kaggle token, see below)
    python scripts/fetch_datasets.py get off-zambia --accept-licence --max-products 500
    python scripts/fetch_datasets.py get osm-lusaka --accept-licence
    python scripts/fetch_datasets.py get creditcard-openml --accept-licence   (no account needed; same ULB data as Kaggle's)
    python scripts/fetch_datasets.py status                                   (what is downloaded)
    python scripts/fetch_datasets.py verify creditcard-openml                 (re-check checksums and the expected columns)

Rules this tool follows (each is covered by tests/test_fetch_datasets.py):
  * NOTHING is downloaded unless you pass --accept-licence. That flag is you confirming you have read the dataset's
    terms (printed by `info`). Several licences are unverified; read the page, do not rely on this tool's summary.
  * Files go to backend/data/external/<name>/, which is git-ignored. Nothing is ever written elsewhere.
  * https only, a size cap (--max-mb, default 600), timeouts, and a zip extractor that refuses paths escaping the folder.
  * Each dataset folder gets MANIFEST.json (source, terms link, date, file sizes, SHA-256) and, where the licence needs
    attribution, ATTRIBUTION.txt. Keep them with the data.
  * Kaggle downloads use YOUR token (%USERPROFILE%\.kaggle\kaggle.json or KAGGLE_USERNAME/KAGGLE_KEY) through the official
    `kaggle` package (pip install kaggle). This tool never reads, stores or prints credentials. For competition datasets you
    must first click "Join competition / accept rules" on the Kaggle website.
  * Public services (Open Food Facts, Overpass) are queried slowly with an identifying User-Agent and retried politely.

Do NOT use these datasets to make real decisions about real customers; see docs/DATASETS.md for what each is good for.
"""
import argparse
import csv
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "external"
USER_AGENT = "store-dataset-tool/1.0 (research use; contact: set DATASET_CONTACT)"
DEFAULT_MAX_MB = 600
CHUNK = 1 << 16

# status: "confirmed" = licence read from the dataset's own page by the project; "unverified" = read the page yourself.
CATALOG = {
    "phiusiil": {
        "title": "PhiUSIIL Phishing URL dataset (UCI #967): 235,795 URLs, 54 features",
        "use": "ScamWatch experiments. Only the features computable from the URL text are usable: ScamWatch never opens links.",
        "kind": "url_zip", "url": "https://archive.ics.uci.edu/static/public/967/phiusiil+phishing+url+dataset.zip",
        "terms": "https://archive.ics.uci.edu/dataset/967/phiusiil+phishing+url+dataset",
        "licence": "CC BY 4.0 (credit the authors: Prasad and Chandra, Computers & Security 2024, doi:10.1016/j.cose.2023.103545)",
        "status": "confirmed", "attribution": "PhiUSIIL Phishing URL Dataset, A. Prasad and S. Chandra, Computers & Security (2024), "
                                              "doi:10.1016/j.cose.2023.103545. CC BY 4.0.", "size": "about 60 MB",
    },
    "paysim": {
        "title": "PaySim: simulated mobile-money transactions (Kaggle ealaxi/paysim1), about 6.3 million rows",
        "use": "Fraud-model experiments for MTN/Airtel-style mobile money. Do NOT use the balance columns as inputs (they leak the label).",
        "kind": "kaggle_dataset", "ref": "ealaxi/paysim1", "terms": "https://www.kaggle.com/datasets/ealaxi/paysim1",
        "licence": "See the Kaggle page. Cite: Lopez-Rojas, Elmir, Axelsson, PaySim, EMSS 2016.", "status": "unverified",
        "attribution": "PaySim, E. A. Lopez-Rojas, A. Elmir, S. Axelsson, EMSS 2016 (Kaggle ealaxi/paysim1).", "size": "about 180 MB",
    },
    "creditcard": {
        "title": "Credit Card Fraud Detection, ULB (Kaggle mlg-ulb/creditcardfraud): 284,807 rows, anonymised PCA features",
        "use": "The project's 'PCA Model Demo' and practice with very rare fraud. Cannot map to store orders.",
        "kind": "kaggle_dataset", "ref": "mlg-ulb/creditcardfraud", "terms": "https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud",
        "licence": "See the Kaggle page.", "status": "unverified",
        "attribution": "Credit Card Fraud Detection, Machine Learning Group ULB (Kaggle mlg-ulb/creditcardfraud).", "size": "about 150 MB",
    },
    "creditcard-openml": {
        "title": "Credit Card Fraud (ULB) from OpenML #1597: 284,807 rows, Time, V1-V28 (PCA), Amount, Class",
        "use": "The real-data model behind the staff 'PCA Model Demo'. An ALTERNATIVE SOURCE for the same ULB data as `creditcard` that needs "
               "no Kaggle account. Anonymised features: store orders can never be mapped onto it.",
        "kind": "url_file", "url": "https://data.openml.org/datasets/0000/1597/dataset_1597.pq", "file": "creditcard_openml.parquet",
        "terms": "https://www.openml.org/search?type=data&id=1597",
        "licence": "OpenML states 'Public'. Cite: Dal Pozzolo, Caelen, Johnson, Bontempi (ULB Machine Learning Group / Worldline).",
        "status": "confirmed", "attribution": "Credit Card Fraud Detection (OpenML 1597), ULB Machine Learning Group and Worldline: "
                                              "Dal Pozzolo, Caelen, Johnson, Bontempi, Calibrating probability with undersampling for unbalanced "
                                              "classification, IEEE SSCI 2015. Licence stated by OpenML: Public.",
        "size": "about 73 MB",
    },
    "ieee-cis": {
        "title": "IEEE-CIS Fraud Detection (Kaggle competition ieee-fraud-detection), about 590,000 e-commerce transactions",
        "use": "Learning which device / email / address signals matter. Competition data: check its rules before any commercial use.",
        "kind": "kaggle_competition", "ref": "ieee-fraud-detection", "terms": "https://www.kaggle.com/c/ieee-fraud-detection/rules",
        "licence": "Competition rules (you must accept them on Kaggle first).", "status": "unverified",
        "attribution": "IEEE-CIS Fraud Detection, Vesta Corporation and the IEEE Computational Intelligence Society (Kaggle, 2019).",
        "size": "about 120 MB", "needs_rules": True,
    },
    "instacart": {
        "title": "Instacart Market Basket Analysis (Kaggle competition), about 3 million grocery orders",
        "use": "Prototyping 'frequently bought together' and 'buy again'. Non-commercial terms are likely: read them.",
        "kind": "kaggle_competition", "ref": "instacart-market-basket-analysis",
        "terms": "https://www.kaggle.com/c/instacart-market-basket-analysis/rules", "licence": "Competition rules.", "status": "unverified",
        "attribution": "The Instacart Online Grocery Shopping Dataset (Kaggle instacart-market-basket-analysis).",
        "size": "about 200 MB", "needs_rules": True,
    },
    "off-zambia": {
        "title": "Open Food Facts products sold in Zambia (queried through the public API, not the multi-GB full dump)",
        "use": "Names, brands, pack sizes, barcodes and image links to enrich YOUR catalogue. Coverage of Zambia may be thin. Never prices.",
        "kind": "off", "url": "https://world.openfoodfacts.org/api/v2/search",
        "terms": "https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/tutorials/license-be-on-the-legal-side/",
        "licence": "Database: ODbL (credit + share-alike on published derivatives). Images: CC BY-SA, may contain third-party material.",
        "status": "confirmed", "attribution": "Contains information from Open Food Facts (openfoodfacts.org), made available under the "
                                              "Open Database License (ODbL). Images: CC BY-SA.", "size": "small",
    },
    "osm-lusaka": {
        "title": "OpenStreetMap suburbs and neighbourhoods around Lusaka (via the Overpass API)",
        "use": "A starting list of area names for the delivery-area picker. Check it by hand: OSM names are volunteer-entered.",
        "kind": "overpass", "url": "https://overpass-api.de/api/interpreter",
        "terms": "https://www.openstreetmap.org/copyright", "licence": "ODbL (credit: © OpenStreetMap contributors).",
        "status": "unverified", "attribution": "© OpenStreetMap contributors, Open Database License (ODbL). openstreetmap.org/copyright",
        "size": "small",
    },
}


# What each downloaded dataset must look like. `verify` and every download check this, so a changed or truncated file is caught.
CREDITCARD_COLUMNS = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount", "Class"]
SCHEMAS = {
    "creditcard-openml": {"file": "creditcard_openml.parquet", "columns": CREDITCARD_COLUMNS, "min_rows": 284_000},
    "phiusiil": {"file": "PhiUSIIL_Phishing_URL_Dataset.csv", "columns": ["URL", "label"], "min_rows": 235_000},
}


class FetchError(Exception):
    """A problem the user can act on. Printed without a traceback."""


# ----------------------------------------------------------------------------------------------------- helpers
def require_https(url: str) -> None:
    if urllib.parse.urlparse(url).scheme != "https":
        raise FetchError(f"Refusing a non-https address: {url}")


def dataset_dir(name: str, root: Path = ROOT) -> Path:
    if name not in CATALOG:
        raise FetchError(f"Unknown dataset '{name}'. Run: python scripts/fetch_datasets.py list")
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def stream_to_file(url: str, dest: Path, max_bytes: int, opener=urllib.request.urlopen, timeout: int = 60) -> str:
    """Download `url` to `dest`, never exceeding `max_bytes`. Returns the SHA-256. Deletes a partial file on any failure."""
    require_https(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    h, total = hashlib.sha256(), 0
    try:
        with opener(req, timeout=timeout) as r, open(dest, "wb") as f:
            declared = r.headers.get("Content-Length") if getattr(r, "headers", None) else None
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise FetchError(f"The file is {int(declared) / 1e6:.0f} MB, above the {max_bytes / 1e6:.0f} MB limit (raise --max-mb).")
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError(f"Download exceeded the {max_bytes / 1e6:.0f} MB limit and was stopped (raise --max-mb).")
                h.update(chunk)
                f.write(chunk)
    except FetchError:
        dest.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        dest.unlink(missing_ok=True)
        raise FetchError(f"Download failed ({type(exc).__name__}: {exc}).") from None
    return h.hexdigest()


def stream_with_retries(url: str, dest: Path, max_bytes: int, opener=urllib.request.urlopen, retries: int = 3, sleep=time.sleep) -> str:
    """stream_to_file, retried on transient network errors (never on a size-limit or https refusal, which cannot succeed later)."""
    last = None
    for attempt in range(retries):
        try:
            return stream_to_file(url, dest, max_bytes, opener)
        except FetchError as exc:
            if "limit" in str(exc) or "non-https" in str(exc):
                raise
            last = exc
            if attempt < retries - 1:
                sleep(min(30, 3 * 2 ** attempt))
    raise last


def check_schema(name: str, folder: Path) -> dict:
    """Confirm the downloaded file has the expected columns and plausible size. Raises FetchError otherwise."""
    spec = SCHEMAS.get(name)
    if spec is None:
        return {"checked": False}
    f = folder / spec["file"]
    if not f.exists():
        raise FetchError(f"Expected file {spec['file']} is missing from {folder}.")
    try:
        if f.suffix == ".parquet":
            import pyarrow.parquet as pq
            pf = pq.ParquetFile(f)
            cols, rows = list(pf.schema_arrow.names), pf.metadata.num_rows
        else:
            with open(f, encoding="utf8", errors="replace") as fh:
                cols = next(csv.reader(fh))
            with open(f, "rb") as fh:
                rows = sum(1 for _ in fh) - 1
    except Exception as exc:                      # corrupt archive / not a parquet file / unreadable
        raise FetchError(f"{spec['file']} could not be read ({type(exc).__name__}): the download may be corrupt.") from None
    missing = [c for c in spec["columns"] if c not in cols]
    if missing:
        raise FetchError(f"{spec['file']} is missing expected columns: {missing[:5]}. Not the dataset this tool expects.")
    if rows < spec["min_rows"]:
        raise FetchError(f"{spec['file']} has only {rows} rows (expected at least {spec['min_rows']}): truncated download?")
    return {"checked": True, "rows": rows, "columns": len(cols)}


def safe_extract(zip_path: Path, dest: Path, max_bytes: int = 5 << 30) -> list[str]:
    """Unzip into `dest`, refusing any member that would land outside it ("zip slip") or that is absurdly large."""
    dest = dest.resolve()
    names = []
    with zipfile.ZipFile(zip_path) as z:
        total = 0
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if dest != target and dest not in target.parents:
                raise FetchError(f"Unsafe path in the archive, nothing extracted: {info.filename}")
            total += info.file_size
            if total > max_bytes:
                raise FetchError("The archive expands to an unreasonable size; nothing extracted.")
        z.extractall(dest)
        names = [i.filename for i in z.infolist() if not i.is_dir()]
    return names


def write_manifest(folder: Path, name: str, source: str, files: list[Path], extra: dict | None = None) -> Path:
    meta = CATALOG[name]
    entries = []
    for f in sorted(files):
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                h.update(chunk)
        entries.append({"file": f.name, "bytes": f.stat().st_size, "sha256": h.hexdigest()})
    manifest = {"dataset": name, "title": meta["title"], "source": source, "terms": meta["terms"], "licence": meta["licence"],
                "licence_status": meta["status"], "downloaded_at": datetime.now(timezone.utc).isoformat(), "files": entries, **(extra or {})}
    (folder / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
    (folder / "ATTRIBUTION.txt").write_text(meta["attribution"] + "\n", encoding="utf8")
    return folder / "MANIFEST.json"


def verify_dataset(name: str, root: Path = ROOT) -> dict:
    """Re-hash every file against MANIFEST.json and re-check the expected columns. Returns a report; raises FetchError if bad."""
    folder = root / name
    manifest_path = folder / "MANIFEST.json"
    if not manifest_path.exists():
        raise FetchError(f"'{name}' has not been downloaded (no MANIFEST.json in {folder}).")
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    problems = []
    for entry in manifest.get("files", []):
        f = folder / entry["file"]
        if not f.exists():
            problems.append(f"missing file {entry['file']}")
            continue
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                h.update(chunk)
        if h.hexdigest() != entry["sha256"] or f.stat().st_size != entry["bytes"]:
            problems.append(f"{entry['file']} changed since it was downloaded (checksum mismatch)")
    schema = {}
    try:
        schema = check_schema(name, folder)
    except FetchError as exc:
        problems.append(str(exc))
    if problems:
        raise FetchError("; ".join(problems))
    return {"dataset": name, "files": len(manifest.get("files", [])), "schema": schema, "licence": manifest.get("licence"),
            "downloaded_at": manifest.get("downloaded_at")}


def http_json(url: str, params: dict | None = None, data: bytes | None = None, retries: int = 4, opener=urllib.request.urlopen,
              sleep=time.sleep) -> dict:
    """A polite JSON call: identifying User-Agent, timeout, and exponential back-off on 429/5xx."""
    require_https(url)
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        try:
            with opener(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
        sleep(min(60, 5 * 2 ** attempt))
    raise FetchError(f"The service did not answer usefully ({last}). It may be busy: try again later.")


# ----------------------------------------------------------------------------------------------------- fetchers
def fetch_url_zip(name: str, folder: Path, max_bytes: int, opener=urllib.request.urlopen) -> list[Path]:
    zip_path = folder / f"{name}.zip"
    stream_with_retries(CATALOG[name]["url"], zip_path, max_bytes, opener)
    names = safe_extract(zip_path, folder)
    zip_path.unlink()
    return [folder / n for n in names]


def fetch_url_file(name: str, folder: Path, max_bytes: int, opener=urllib.request.urlopen, sleep=time.sleep) -> list[Path]:
    """One file over https (not an archive). Downloaded to a .part file and moved into place only when complete."""
    meta = CATALOG[name]
    final = folder / meta["file"]
    part = folder / (meta["file"] + ".part")
    try:
        stream_with_retries(meta["url"], part, max_bytes, opener, sleep=sleep)
        part.replace(final)
    finally:
        part.unlink(missing_ok=True)
    return [final]


def fetch_kaggle(name: str, folder: Path) -> list[Path]:
    meta = CATALOG[name]
    token = Path.home() / ".kaggle" / "kaggle.json"
    import os
    if not token.exists() and not (os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY")):
        raise FetchError("No Kaggle credentials found. Create an API token on kaggle.com (Settings > API) and save kaggle.json in "
                         f"{token.parent}, or download '{meta['ref']}' by hand from {meta['terms']}.")
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        raise FetchError("The 'kaggle' package is not installed. Run: pip install kaggle") from None
    try:
        api = KaggleApi()
        api.authenticate()
        if meta["kind"] == "kaggle_competition":
            api.competition_download_files(meta["ref"], path=str(folder), quiet=False)
            for z in folder.glob("*.zip"):
                safe_extract(z, folder)
                z.unlink()
        else:
            api.dataset_download_files(meta["ref"], path=str(folder), unzip=True)
    except FetchError:
        raise
    except Exception as exc:                  # auth, terms/rules not accepted, network, rate limit
        hint = " Join the competition and accept its rules on the Kaggle website first." if meta.get("needs_rules") else \
            " Accept the dataset terms on the Kaggle website and check your token."
        raise FetchError(f"Kaggle download failed ({type(exc).__name__}).{hint}") from None
    files = [p for p in folder.iterdir() if p.is_file() and p.name not in ("MANIFEST.json", "ATTRIBUTION.txt")]
    if not files:
        raise FetchError("Kaggle finished but no files were found.")
    return files


OFF_FIELDS = "code,product_name,brands,quantity,categories_tags,countries_tags,image_front_url,image_front_small_url,nutriscore_grade,last_modified_t"


def off_rows(products: list[dict]) -> list[dict]:
    rows = []
    for p in products:
        if not p.get("code") or not (p.get("product_name") or "").strip():
            continue                            # a barcode with no name is no use for a catalogue
        rows.append({"barcode": p["code"], "name": p["product_name"].strip(), "brand": (p.get("brands") or "").split(",")[0].strip(),
                     "pack_size": (p.get("quantity") or "").strip(), "categories": ";".join(p.get("categories_tags") or []),
                     "image_url": p.get("image_front_url") or "", "image_small_url": p.get("image_front_small_url") or "",
                     "nutriscore": p.get("nutriscore_grade") or ""})
    return rows


def fetch_off(folder: Path, max_products: int = 500, country: str = "zambia", http=http_json, sleep=time.sleep) -> list[Path]:
    """Page through Open Food Facts search results slowly (their API asks for gentle use). Writes products.csv."""
    rows, page = [], 1
    while len(rows) < max_products:
        d = http(CATALOG["off-zambia"]["url"], {"countries_tags_en": country, "fields": OFF_FIELDS, "page_size": 100, "page": page})
        batch = d.get("products") or []
        if not batch:
            break
        rows.extend(off_rows(batch))
        if page * int(d.get("page_size") or 100) >= int(d.get("count") or 0):
            break
        page += 1
        sleep(7)                                # search is rate limited (about 10 a minute): stay well under it
    rows = rows[:max_products]
    out = folder / "products.csv"
    with open(out, "w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=["barcode", "name", "brand", "pack_size", "categories", "image_url", "image_small_url", "nutriscore"])
        w.writeheader()
        w.writerows(rows)
    if not rows:
        raise FetchError(f"Open Food Facts returned no named products for '{country}'. Coverage may be thin: try another country tag "
                         "or add barcodes by hand.")
    return [out]


def overpass_query(area: str) -> str:
    safe = "".join(ch for ch in area if ch.isalnum() or ch in " -'")[:60]
    return (f'[out:json][timeout:90];area["ISO3166-1"="ZM"]->.z;area["name"="{safe}"](area.z)->.a;'
            '(node["place"~"^(suburb|neighbourhood|quarter|village|town)$"](area.a);way["place"~"^(suburb|neighbourhood|quarter)$"](area.a););out center tags;')


def overpass_rows(data: dict) -> list[dict]:
    rows, seen = [], set()
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        centre = el if "lat" in el else el.get("center") or {}
        if not name or name.lower() in seen or "lat" not in centre:
            continue
        seen.add(name.lower())
        rows.append({"name": name, "place": tags.get("place", ""), "lat": centre["lat"], "lon": centre["lon"],
                     "osm_type": el.get("type", ""), "osm_id": el.get("id", "")})
    return sorted(rows, key=lambda r: r["name"].lower())


def fetch_overpass(folder: Path, area: str = "Lusaka", http=http_json) -> list[Path]:
    body = urllib.parse.urlencode({"data": overpass_query(area)}).encode()
    rows = overpass_rows(http(CATALOG["osm-lusaka"]["url"], data=body))
    if not rows:
        raise FetchError(f"OpenStreetMap returned no named places for '{area}'.")
    out = folder / "areas.csv"
    with open(out, "w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "place", "lat", "lon", "osm_type", "osm_id"])
        w.writeheader()
        w.writerows(rows)
    return [out]


# ----------------------------------------------------------------------------------------------------- command line
def cmd_list() -> int:
    for name, m in CATALOG.items():
        print(f"{name:11} [{m['status']:10}] {m['size']:>13}  {m['title']}")
    print("\nstatus 'unverified' = the licence was not confirmed by the project: read the terms page before using the data.")
    return 0


def cmd_info(name: str) -> int:
    if name not in CATALOG:
        raise FetchError(f"Unknown dataset '{name}'.")
    m = CATALOG[name]
    print(f"{name}: {m['title']}\n  Good for : {m['use']}\n  Licence  : {m['licence']} [{m['status']}]\n  Terms    : {m['terms']}\n  Size     : {m['size']}")
    return 0


def cmd_status(root: Path = ROOT) -> int:
    for name in CATALOG:
        m = root / name / "MANIFEST.json"
        if m.exists():
            d = json.loads(m.read_text(encoding="utf8"))
            print(f"{name:18} downloaded {d.get('downloaded_at', '?')[:19]}  {len(d.get('files', []))} file(s)")
        else:
            print(f"{name:18} not downloaded")
    return 0


def cmd_verify(name: str, root: Path = ROOT) -> int:
    if name not in CATALOG:
        raise FetchError(f"Unknown dataset '{name}'.")
    r = verify_dataset(name, root)
    print(f"OK {name}: {r['files']} file(s) match their checksums; schema {r['schema'] or 'not defined for this dataset'}")
    return 0


def cmd_get(args, root: Path = ROOT) -> int:
    if args.name not in CATALOG:
        raise FetchError(f"Unknown dataset '{args.name}'.")
    meta = CATALOG[args.name]
    if not args.accept_licence:
        print(f"Not downloading. Read the terms first:\n  {meta['terms']}\nLicence: {meta['licence']} [{meta['status']}]\n"
              f"Then run again with --accept-licence to confirm you accept them.")
        return 2
    folder = dataset_dir(args.name, root)
    if (folder / "MANIFEST.json").exists() and not args.force:
        print(f"Already downloaded: {folder} (use --force to fetch again).")
        return 0
    max_bytes = int(args.max_mb * 1_000_000)
    kind = meta["kind"]
    if kind == "url_zip":
        files = fetch_url_zip(args.name, folder, max_bytes)
    elif kind == "url_file":
        files = fetch_url_file(args.name, folder, max_bytes)
    elif kind in ("kaggle_dataset", "kaggle_competition"):
        files = fetch_kaggle(args.name, folder)
    elif kind == "off":
        files = fetch_off(folder, args.max_products, args.country)
    else:
        files = fetch_overpass(folder, args.area)
    schema = check_schema(args.name, folder)           # a corrupt or wrong file is reported now, not at training time
    manifest = write_manifest(folder, args.name, meta.get("url") or meta.get("ref", ""), [f for f in files if f.is_file()],
                              {"schema_check": schema})
    print(f"Saved {len(files)} file(s) in {folder}\nRecorded {manifest.name} and ATTRIBUTION.txt: keep them with the data.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("status")
    v = sub.add_parser("verify"); v.add_argument("name")
    i = sub.add_parser("info"); i.add_argument("name")
    g = sub.add_parser("get"); g.add_argument("name")
    g.add_argument("--accept-licence", action="store_true", help="I have read the dataset's terms and accept them")
    g.add_argument("--force", action="store_true"); g.add_argument("--max-mb", type=float, default=DEFAULT_MAX_MB)
    g.add_argument("--max-products", type=int, default=500); g.add_argument("--country", default="zambia"); g.add_argument("--area", default="Lusaka")
    args = p.parse_args(argv)
    try:
        if args.cmd == "list":
            return cmd_list()
        if args.cmd == "status":
            return cmd_status()
        if args.cmd == "verify":
            return cmd_verify(args.name)
        return cmd_info(args.name) if args.cmd == "info" else cmd_get(args)
    except FetchError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
