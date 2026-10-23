"""scripts/fetch_datasets.py: licence gate, size caps, safe unzip, manifests, and parsing. No test touches the network."""
import importlib.util
import io
import json
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("fetch_datasets", Path(__file__).resolve().parents[1] / "scripts" / "fetch_datasets.py")
fd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fd)


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, declared=None):
        super().__init__(body)
        self.headers = {"Content-Length": str(declared if declared is not None else len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def args(name, **over):
    base = dict(name=name, accept_licence=False, force=False, max_mb=600, max_products=50, country="zambia", area="Lusaka")
    base.update(over)
    return SimpleNamespace(**base)


# ------------------------------------------------------------------------------------------------- catalogue + gate
def test_every_catalogue_entry_is_complete_and_https():
    assert set(fd.CATALOG) == {"phiusiil", "paysim", "creditcard", "creditcard-openml", "ieee-cis", "instacart", "off-zambia", "osm-lusaka"}
    for name, m in fd.CATALOG.items():
        for key in ("title", "use", "kind", "terms", "licence", "status", "attribution", "size"):
            assert m.get(key), (name, key)
        assert m["terms"].startswith("https://") and m["status"] in ("confirmed", "unverified")
        if m["kind"] in ("url_zip", "url_file", "off", "overpass"):
            assert m["url"].startswith("https://")
    assert fd.CATALOG["phiusiil"]["status"] == "confirmed" and "CC BY 4.0" in fd.CATALOG["phiusiil"]["licence"]


def test_nothing_is_downloaded_without_accepting_the_licence(tmp_path, capsys):
    called = []
    assert fd.cmd_get(args("phiusiil"), tmp_path) == 2
    out = capsys.readouterr().out
    assert "Read the terms first" in out and "--accept-licence" in out and not called
    assert not (tmp_path / "phiusiil").exists()                         # not even the folder is created


def test_unknown_dataset_and_cli_errors_are_friendly(capsys):
    assert fd.main(["info", "nope"]) == 1 and "Unknown dataset" in capsys.readouterr().out
    assert fd.main(["list"]) == 0 and "phiusiil" in capsys.readouterr().out
    assert fd.main(["info", "paysim"]) == 0 and "unverified" in capsys.readouterr().out
    assert fd.main(["get", "paysim"]) == 2


def test_data_goes_only_under_the_git_ignored_external_folder():
    assert fd.ROOT.parts[-3:] == ("backend", "data", "external")
    root = Path(__file__).resolve().parents[2]
    ignore = (root / ".gitignore").read_text()
    assert "backend/data/external/" in ignore


# ------------------------------------------------------------------------------------------------- downloading safely
def test_https_only():
    with pytest.raises(fd.FetchError, match="non-https"):
        fd.require_https("http://example.com/x.zip")
    with pytest.raises(fd.FetchError, match="non-https"):
        fd.stream_to_file("http://example.com/x.zip", Path("x"), 10)


def test_stream_enforces_the_size_cap_and_deletes_partial_files(tmp_path):
    dest = tmp_path / "f.zip"
    declared = lambda req, timeout: FakeResponse(b"x" * 10, declared=5_000_000)           # noqa: E731
    with pytest.raises(fd.FetchError, match="above the"):
        fd.stream_to_file("https://example.com/f.zip", dest, 1000, declared)
    assert not dest.exists()
    liar = lambda req, timeout: FakeResponse(b"x" * 5000, declared=10)                    # lies about its size  # noqa: E731
    with pytest.raises(fd.FetchError, match="exceeded"):
        fd.stream_to_file("https://example.com/f.zip", dest, 1000, liar)
    assert not dest.exists()


def test_stream_reports_network_errors_without_a_traceback(tmp_path):
    def boom(req, timeout):
        raise urllib.error.URLError("no route")
    with pytest.raises(fd.FetchError, match="Download failed"):
        fd.stream_to_file("https://example.com/f.zip", tmp_path / "f.zip", 1000, boom)
    assert not (tmp_path / "f.zip").exists()


def test_zip_slip_is_refused(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(zip_bytes({"../../evil.txt": "pwned", "ok.csv": "a,b"}))
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(fd.FetchError, match="Unsafe path"):
        fd.safe_extract(bad, dest)
    assert not (tmp_path / "evil.txt").exists() and not list(dest.iterdir())            # nothing at all was extracted


def test_a_normal_zip_extracts_and_a_full_download_writes_a_manifest(tmp_path):
    body = zip_bytes({"PhiUSIIL_Phishing_URL_Dataset.csv": "URL,label\nhttp://a.b,1\n", "readme.txt": "hi"})
    folder = fd.dataset_dir("phiusiil", tmp_path)
    files = fd.fetch_url_zip("phiusiil", folder, 10_000_000, lambda req, timeout: FakeResponse(body))
    assert sorted(p.name for p in files) == ["PhiUSIIL_Phishing_URL_Dataset.csv", "readme.txt"]
    assert not (folder / "phiusiil.zip").exists()                                         # the archive is removed
    manifest = fd.write_manifest(folder, "phiusiil", "https://example.test/src", files)
    m = json.loads(manifest.read_text())
    assert m["dataset"] == "phiusiil" and m["licence_status"] == "confirmed" and len(m["files"]) == 2
    assert all(len(f["sha256"]) == 64 and f["bytes"] > 0 for f in m["files"])
    assert "CC BY 4.0" in (folder / "ATTRIBUTION.txt").read_text()


def test_get_skips_a_dataset_already_downloaded_unless_forced(tmp_path, capsys, monkeypatch):
    folder = fd.dataset_dir("phiusiil", tmp_path)
    (folder / "MANIFEST.json").write_text("{}")
    monkeypatch.setattr(fd, "fetch_url_zip", lambda *a, **k: pytest.fail("should not download again"))
    assert fd.cmd_get(args("phiusiil", accept_licence=True), tmp_path) == 0
    assert "Already downloaded" in capsys.readouterr().out


def test_get_runs_end_to_end_with_a_fake_download(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(fd.SCHEMAS, "phiusiil", {"file": "data.csv", "columns": ["URL", "label"], "min_rows": 1})
    body = zip_bytes({"data.csv": "URL,label\nhttp://a.b,1\n"})
    monkeypatch.setattr(fd, "stream_to_file", lambda url, dest, max_bytes, opener=None, timeout=60: Path(dest).write_bytes(body) or "x")
    assert fd.cmd_get(args("phiusiil", accept_licence=True), tmp_path) == 0
    assert (tmp_path / "phiusiil" / "data.csv").exists() and (tmp_path / "phiusiil" / "MANIFEST.json").exists()
    assert "keep them with the data" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------- kaggle (no credentials)
def test_kaggle_without_credentials_explains_what_to_do(tmp_path, monkeypatch):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))                  # a home directory with no kaggle.json
    with pytest.raises(fd.FetchError, match="No Kaggle credentials"):
        fd.fetch_kaggle("paysim", tmp_path)


# ------------------------------------------------------------------------------------------------- open food facts + osm
OFF_PAGE = {"count": 3, "page": 1, "page_size": 100, "products": [
    {"code": "6001", "product_name": " Mealie Meal 10kg ", "brands": "Impala, Other", "quantity": "10 kg", "categories_tags": ["en:flours", "en:maize"],
     "image_front_url": "https://images.openfoodfacts.org/a.jpg"},
    {"code": "6002", "product_name": "", "brands": "NoName"},                              # no name: dropped
    {"product_name": "No barcode"},                                                         # no barcode: dropped
    {"code": "6003", "product_name": "Cooking Oil", "brands": None, "quantity": None}]}


def test_off_rows_keep_only_usable_products():
    rows = fd.off_rows(OFF_PAGE["products"])
    assert [r["barcode"] for r in rows] == ["6001", "6003"]
    assert rows[0] == {"barcode": "6001", "name": "Mealie Meal 10kg", "brand": "Impala", "pack_size": "10 kg", "categories": "en:flours;en:maize",
                       "image_url": "https://images.openfoodfacts.org/a.jpg", "image_small_url": "", "nutriscore": ""}
    assert rows[1]["brand"] == "" and rows[1]["pack_size"] == ""


def test_fetch_off_pages_politely_and_writes_a_csv(tmp_path):
    sleeps, calls = [], []

    def http(url, params=None, **kw):
        calls.append(params["page"])
        return {"count": 250, "page_size": 100, "products": OFF_PAGE["products"] if params["page"] < 3 else []}
    out = fd.fetch_off(tmp_path, max_products=10, http=http, sleep=sleeps.append)
    assert calls == [1, 2, 3] and sleeps == [7, 7]                                          # a pause between every page
    lines = out[0].read_text(encoding="utf8").splitlines()
    assert lines[0].startswith("barcode,name,brand") and len(lines) == 1 + 4


def test_fetch_off_says_so_when_zambia_has_no_products(tmp_path):
    with pytest.raises(fd.FetchError, match="(?i)coverage may be thin"):
        fd.fetch_off(tmp_path, http=lambda *a, **k: {"count": 0, "products": []}, sleep=lambda s: None)


def test_http_json_retries_busy_services_then_gives_up():
    attempts, naps = [], []

    def busy(req, timeout):
        attempts.append(1)
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
    with pytest.raises(fd.FetchError, match="try again later"):
        fd.http_json("https://example.com/x", retries=3, opener=busy, sleep=naps.append)
    assert len(attempts) == 3 and naps == [5, 10, 20]                                       # exponential back-off
    attempts.clear()

    def forbidden(req, timeout):
        attempts.append(1)
        raise urllib.error.HTTPError(req.full_url, 403, "no", {}, None)
    with pytest.raises(fd.FetchError):
        fd.http_json("https://example.com/x", retries=3, opener=forbidden, sleep=lambda s: None)
    assert len(attempts) == 1                                                               # not retried: it will never work


def test_http_json_succeeds_after_a_transient_failure():
    seq = [urllib.error.HTTPError("https://x", 503, "busy", {}, None), FakeResponse(b'{"ok": true}')]

    def opener(req, timeout):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    assert fd.http_json("https://example.com/x", opener=opener, sleep=lambda s: None) == {"ok": True}


def test_overpass_query_is_safe_and_rows_are_deduplicated():
    q = fd.overpass_query('Lusaka"];out;//')
    assert '"];' not in q.split('"name"="')[1].split('"')[0] and "ISO3166-1" in q
    data = {"elements": [
        {"type": "node", "id": 1, "lat": -15.4, "lon": 28.3, "tags": {"name": "Kabulonga", "place": "suburb"}},
        {"type": "way", "id": 2, "center": {"lat": -15.5, "lon": 28.2}, "tags": {"name": "Woodlands", "place": "suburb"}},
        {"type": "node", "id": 3, "lat": 0, "lon": 0, "tags": {"name": "kabulonga", "place": "suburb"}},        # duplicate name
        {"type": "node", "id": 4, "lat": 0, "lon": 0, "tags": {"place": "suburb"}}]}                           # no name
    rows = fd.overpass_rows(data)
    assert [r["name"] for r in rows] == ["Kabulonga", "Woodlands"] and rows[1]["lat"] == -15.5


def test_fetch_overpass_writes_areas_csv(tmp_path):
    out = fd.fetch_overpass(tmp_path, "Lusaka", http=lambda url, **k: {"elements": [
        {"type": "node", "id": 1, "lat": -15.4, "lon": 28.3, "tags": {"name": "Rhodes Park", "place": "suburb"}}]})
    assert "Rhodes Park" in out[0].read_text()
    with pytest.raises(fd.FetchError):
        fd.fetch_overpass(tmp_path, "Nowhere", http=lambda url, **k: {"elements": []})


# ------------------------------------------------------------------------------------------------- schema + verify + retries
def parquet_fixture(path: Path, columns, rows=3):
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.table({c: [0.0] * rows for c in columns}), path)


def test_check_schema_accepts_the_expected_file_and_rejects_wrong_truncated_or_corrupt_ones(tmp_path, monkeypatch):
    monkeypatch.setitem(fd.SCHEMAS, "creditcard-openml", {"file": "c.parquet", "columns": fd.CREDITCARD_COLUMNS, "min_rows": 3})
    parquet_fixture(tmp_path / "c.parquet", fd.CREDITCARD_COLUMNS)
    assert fd.check_schema("creditcard-openml", tmp_path) == {"checked": True, "rows": 3, "columns": 31}
    parquet_fixture(tmp_path / "c.parquet", ["a", "b"])
    with pytest.raises(fd.FetchError, match="missing expected columns"):
        fd.check_schema("creditcard-openml", tmp_path)
    parquet_fixture(tmp_path / "c.parquet", fd.CREDITCARD_COLUMNS, rows=2)
    with pytest.raises(fd.FetchError, match="truncated"):
        fd.check_schema("creditcard-openml", tmp_path)
    (tmp_path / "c.parquet").write_bytes(b"not a parquet file")
    with pytest.raises(fd.FetchError, match="corrupt"):
        fd.check_schema("creditcard-openml", tmp_path)
    (tmp_path / "c.parquet").unlink()
    with pytest.raises(fd.FetchError, match="missing"):
        fd.check_schema("creditcard-openml", tmp_path)
    assert fd.check_schema("paysim", tmp_path) == {"checked": False}                      # no schema defined: not pretended


def test_a_single_file_download_is_atomic_and_verified(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(fd.SCHEMAS, "creditcard-openml", {"file": "creditcard_openml.parquet", "columns": fd.CREDITCARD_COLUMNS, "min_rows": 3})
    src = tmp_path / "src.parquet"
    parquet_fixture(src, fd.CREDITCARD_COLUMNS)
    body = src.read_bytes()
    monkeypatch.setattr(fd, "stream_with_retries", lambda url, dest, mb, opener=None, sleep=None: Path(dest).write_bytes(body) or "x")
    root = tmp_path / "ext"
    assert fd.cmd_get(args("creditcard-openml", accept_licence=True), root) == 0
    folder = root / "creditcard-openml"
    assert (folder / "creditcard_openml.parquet").exists() and not list(folder.glob("*.part"))
    m = json.loads((folder / "MANIFEST.json").read_text())
    assert m["schema_check"]["rows"] == 3 and m["licence_status"] == "confirmed" and "OpenML" in m["source"] + m["title"]
    assert fd.cmd_verify("creditcard-openml", root) == 0 and "OK creditcard-openml" in capsys.readouterr().out
    assert fd.cmd_status(root) == 0 and "creditcard-openml" in capsys.readouterr().out


def test_verify_detects_tampering_and_missing_downloads(tmp_path, monkeypatch):
    monkeypatch.setitem(fd.SCHEMAS, "creditcard-openml", {"file": "creditcard_openml.parquet", "columns": fd.CREDITCARD_COLUMNS, "min_rows": 3})
    with pytest.raises(fd.FetchError, match="has not been downloaded"):
        fd.verify_dataset("creditcard-openml", tmp_path)
    folder = fd.dataset_dir("creditcard-openml", tmp_path)
    parquet_fixture(folder / "creditcard_openml.parquet", fd.CREDITCARD_COLUMNS)
    fd.write_manifest(folder, "creditcard-openml", "src", [folder / "creditcard_openml.parquet"])
    assert fd.verify_dataset("creditcard-openml", tmp_path)["files"] == 1
    parquet_fixture(folder / "creditcard_openml.parquet", fd.CREDITCARD_COLUMNS, rows=9)  # file replaced after the manifest was written
    with pytest.raises(fd.FetchError, match="checksum mismatch"):
        fd.verify_dataset("creditcard-openml", tmp_path)


def test_file_downloads_are_retried_but_limits_and_http_refusals_are_not(tmp_path):
    attempts, naps = [], []

    def flaky(req, timeout):
        attempts.append(1)
        if len(attempts) < 3:
            raise urllib.error.URLError("reset")
        return FakeResponse(b"data")
    assert len(fd.stream_with_retries("https://example.com/f", tmp_path / "f", 1000, flaky, sleep=naps.append)) == 64
    assert len(attempts) == 3 and naps == [3, 6]
    attempts.clear()
    with pytest.raises(fd.FetchError, match="above the"):
        fd.stream_with_retries("https://example.com/f", tmp_path / "g", 1, lambda r, timeout: attempts.append(1) or FakeResponse(b"xx", 99), sleep=naps.append)
    assert len(attempts) == 1                                                             # a size-limit refusal is final
    with pytest.raises(fd.FetchError, match="non-https"):
        fd.stream_with_retries("http://example.com/f", tmp_path / "h", 1000)


def test_downloader_tests_never_touch_the_real_data_folder():
    real = fd.ROOT
    before = sorted(p.name for p in real.iterdir()) if real.exists() else None
    assert fd.cmd_status(Path("/nonexistent-root-for-test")) == 0                         # reads only
    assert (sorted(p.name for p in real.iterdir()) if real.exists() else None) == before
