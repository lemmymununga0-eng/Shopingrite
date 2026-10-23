"""CI helper: turn a pytest JUnit report into GitHub Actions annotations so failures are visible without downloading logs.

    python -m pytest -q --junitxml=junit.xml ; python scripts/ci_annotate.py junit.xml

Prints one `::error` line per failed or errored test (first 25) and a `::notice` with the environment. Never fails by itself.
"""
import platform
import sys
import xml.etree.ElementTree as ET


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main(path: str) -> int:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"::error::no readable JUnit report ({type(exc).__name__}); pytest may have crashed before writing it")
        return 0
    try:
        import sklearn
        sk = sklearn.__version__
    except Exception:                                   # pragma: no cover
        sk = "n/a"
    print(f"::notice title=environment::python {platform.python_version()} on {platform.platform()}, scikit-learn {sk}")
    bad = []
    for case in root.iter("testcase"):
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is not None:
                bad.append((case.get("classname", ""), case.get("name", ""), kind, (node.get("message") or "")[:300], (node.text or "")[-1200:]))
    print(f"::notice title=summary::{len(bad)} failed or errored tests")
    for cls, name, kind, msg, text in bad[:25]:
        print(f"::error title={esc(kind)} {esc(cls)}.{esc(name)}::{esc(msg)}%0A{esc(text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "junit.xml"))
