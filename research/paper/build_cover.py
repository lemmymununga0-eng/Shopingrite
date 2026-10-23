"""Cover letter for the journal submission (docx), built with the same renderer as the manuscript.   python build_cover.py"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _common import load  # noqa: E402

A = json.loads((HERE / "author.json").read_text(encoding="utf8"))
cp = load("card_protocol")["rows"]
content_title = json.loads((HERE / "content.json").read_text(encoding="utf8"))["meta"]["docTitle"]

paras = [
    "[Date]",
    "The Editor-in-Chief\nInternational Journal of Advanced Multidisciplinary Research and Studies",
    "Dear Editor,",
    f"Please consider the enclosed manuscript, \"{content_title}\", for publication as an original research article.",
    "The paper addresses a practical problem for small online retailers that accept mobile money and card payments: how to flag risky orders when the store has no fraud-labelled history. "
    "It describes a rule-based assessment for a Zambian online grocery store, a guard that refuses to score inputs a trained model has never seen, and a protocol for collecting "
    "analyst-verified labels. On two public datasets it also measures how much common evaluation shortcuts inflate reported scores. In the experiment, oversampling before the split raised "
    f"a random forest's area under the precision-recall curve on card data from {cp[0]['pr_auc']:.2f} to {cp[1]['pr_auc']:.2f}.",
    "The manuscript is original, has not been published, and is not under review elsewhere. The datasets are public and cited with their licences, and the code, tests and saved results "
    "are in an open repository. An AI assistant helped to write the software, the analysis scripts and the text; this is disclosed in the Acknowledgement. "
    "I confirm that the author details, conflict-of-interest statement and funding statement in the manuscript are accurate.",
    "The manuscript follows the journal's format: A4 pages, Times New Roman 10 pt, a title page with the corresponding author's address at the lower left, an abstract of fewer than 250 words, six keywords, "
    "and numbered references in the journal's author-initials style. The signed author responsibility form is attached.",
    "Yours sincerely,",
    "[Surname], [Given name]\n[Department], [University or organisation], [City], [Country]\nE-mail: lemmymununga0@gmail.com",
]
blocks = []
for p in paras:
    for i, line in enumerate(p.split("\n")):
        blocks.append({"t": "p", "text": line, "align": "left"})
    blocks.append({"t": "p", "text": " ", "align": "left"})
content = {"meta": {"creator": A["creator"], "docTitle": "Cover letter", "description": "Cover letter", "corresponding": [], "noFooter": True}, "blocks": blocks}
(HERE / "cover_content.json").write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf8")
env = dict(os.environ)
if os.environ.get("PAPER_NODE_MODULES"):
    env["NODE_PATH"] = os.environ["PAPER_NODE_MODULES"]
r = subprocess.run(["node", str(HERE / "render_docx.js"), str(HERE / "cover_content.json"), str(HERE / "cover_letter.docx")], capture_output=True, text=True, env=env)
print(r.stdout.strip() or r.stderr.strip())
