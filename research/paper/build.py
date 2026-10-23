"""Builds the manuscript content (content.json) from the saved experiment results and renders it to .docx with render_docx.js.

    python research/paper/build.py            # writes research/paper/content.json and the .docx next to it

Every number in the text and tables is read from research/results/*.json (or from the application code for the schema and rules),
so the paper cannot drift from the experiments. Citations are written as [[Key]], [[Key1;Key2]], [[n:Key]] (narrative) or [[Key|p. 3]].
Table and figure references are written {T:key} and {F:key}.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from _common import ROOT, load  # noqa: E402
from refs import REFS  # noqa: E402

sys.path.insert(0, str(ROOT / "backend"))
from app.ml import store_schema  # noqa: E402
from tests.test_route_security import PUBLIC  # noqa: E402  (the reviewed list of anonymous operations)

AUTHOR = json.loads((HERE / "author.json").read_text(encoding="utf8"))

cb, cp, cs, cl, ci_, clat = (load(n) for n in ("card_benchmark", "card_protocol", "card_seeds", "card_learning_curve", "card_importance", "card_latency"))
crk, ce = load("card_ranking_profile"), load("card_calibration_effect")
pb, pa, pc, pi = (load(n) for n in ("phishing_benchmark", "phishing_ablation", "phishing_controlled", "phishing_importance"))
ppt, phm, psp, pss = load("phishing_perturbation"), load("phishing_host_model"), load("phishing_spot_checks"), load("phishing_score_spread")
ss, sl, sf = (load(n) for n in ("store_scenarios", "store_latency", "store_facts"))
tr_ = load("test_runs")
CM, PM = cb["models"], pb["models"]
RF, LR, HG = CM["random_forest"], CM["logistic_regression"], CM["hist_gradient_boosting"]
PLR, PRF, PHG = PM["logistic_regression"], PM["random_forest"], PM["hist_gradient_boosting"]
HM, HMLR = phm["models"]["hist_gradient_boosting"], phm["models"]["logistic_regression"]
FAM = ["logistic_regression", "random_forest", "hist_gradient_boosting"]
N_SCEN = len(ss["scenarios"])
NUM_WORD = {9: "nine", 10: "ten", 11: "eleven"}


MINUS = chr(0x2212)


def f(x, d=3):
    return f"{x:.{d}f}".replace("-", MINUS)


def pc_(x, d=1):
    return f"{100 * x:.{d}f}%".replace("-", MINUS)


def n_(x):
    return f"{int(x):,}"


def pval(p):
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def band(boot, fam, k, d=3):
    b = boot["ci95"][fam][k]
    return f"{b['lo']:.{d}f} to {b['hi']:.{d}f}"


def band_br(boot, fam, k, d=3):
    b = boot["ci95"][fam][k]
    return f"[{b['lo']:.{d}f}, {b['hi']:.{d}f}]"


def paired(boot, a, b, k="pr_auc"):
    return boot["paired_differences"][f"{a} - {b} [{k}]"]


# ------------------------------------------------------------------------------------------------------------ citations
CITE_ORDER = []                 # reference keys in order of first citation: the journal numbers references in this order


def cite_number(key):
    if key not in REFS:
        raise KeyError(f"unknown reference {key}")
    if key not in CITE_ORDER:
        CITE_ORDER.append(key)
    return CITE_ORDER.index(key) + 1


def compress(numbers):
    """[1, 2, 3, 5] -> '1-3, 5'. Only runs of three or more become a range."""
    out, i, nums = [], 0, sorted(set(numbers))
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(f"{nums[i]}-{nums[j]}" if j - i >= 2 else ", ".join(str(n) for n in nums[i:j + 1]))
        i = j + 1
    return ", ".join(out)


def cite_text(m):
    body = m.group(1)
    narrative = body.startswith("n:")
    if narrative:
        body = body[2:]
    items = []
    for part in body.split(";"):
        key, _, page = part.partition("|")
        key = key.strip()
        items.append((key, cite_number(key), page.strip()))
    if narrative:                                         # "Hayat and Magnier [12]"
        key, n, pg = items[0]
        return f"{REFS[key][0]} [{n}{', ' + pg if pg else ''}]"
    if any(pg for _, _, pg in items):                     # page numbers: "[1, pp. 3, 14]"
        return "[" + "; ".join(f"{n}{', ' + pg if pg else ''}" for _, n, pg in sorted(items, key=lambda t: t[1])) + "]"
    return "[" + compress([n for _, n, _ in items]) + "]"


def T(s):
    return re.sub(r"\[\[([^\]]+)\]\]", cite_text, s).strip()


blocks = []


def add(t, **kw):
    blocks.append({"t": t, **kw})


def P(s):
    add("p", text=T(s))


def H1(s):
    add("h1", text=s)


def H2(s):
    add("h2", text=s)


def H3(s):
    add("h3", text=s)


def BUL(items):
    add("bullets", items=[T(i) for i in items])


def NUM(items):
    add("numbered", items=[T(i) for i in items])


def TAB(key, caption, header, rows, widths, note=None, **kw):
    add("table", key=key, caption=T(caption), header=header, rows=[[T(str(c)) for c in r] for r in rows], widths=widths, note=T(note) if note else None, **kw)


def FIG(key, name, caption, width=6.2):
    add("figure", key=key, path=str((ROOT / "research" / "figures" / name).resolve()).replace("\\", "/"), caption=T(caption), widthIn=width)


# ============================================================================================================ front matter
TITLE = "Auditable fraud-risk assessment for a Zambian online grocery store: leakage-controlled benchmarks and a protocol for collecting verified labels"

n_card_rows = cb["cleaning"]["rows_after"]
card_fraud = RF["split"]["train_class_counts"]["fraud"] + RF["split"]["test_class_counts"]["fraud"]
ph_rows = pb["cleaning"]["rows_after"]
ph_pos = PLR["split"]["train_class_counts"]["fraud"] + PLR["split"]["test_class_counts"]["fraud"]
protoA, protoB, protoC = cp["rows"]
sh = pc["share_of_class"]
TEMPLATE = "exact legitimate template (https, www, no path)"
sub_t = pc["subsets"][TEMPLATE]
sub_b = pc["subsets"]["bare HTTPS site root"]
rewrite_orig = ppt["phishing"]["rewrite as https://www.<host> (legitimate template)"]["flagged_share"]
rel_orig = ppt["phishing"]["as released"]["flagged_share"]

ABSTRACT = (
    "Small online retailers in sub-Saharan Africa take payment by mobile money and card, but they rarely hold the fraud-labelled data that supervised detection needs. "
    "This study builds and tests a risk-assessment framework for a Zambian online grocery store. A transparent rule engine scores every order. Trained models are consulted only "
    "when an order has the fields they were trained on; otherwise the system reports an explicit unsupported status and creates no score. Analysts record verified outcomes for later training. "
    f"We tested the training protocol on two public datasets, {n_(n_card_rows)} card transactions ({card_fraud} frauds) and {n_(ph_rows)} web addresses ({n_(ph_pos)} phishing), "
    "splitting before any fitting, grouping addresses by website and choosing thresholds without the test data. "
    f"On held-out card data a random forest reached an area under the precision-recall curve of {f(RF['test']['pr_auc'])} (95% confidence interval {band(cb['bootstrap'], 'random_forest', 'pr_auc')}); "
    f"oversampling before the split inflated the same model to {f(protoB['pr_auc'], 2)}. "
    f"On web addresses a logistic model scored {f(PLR['test']['pr_auc'])}, but every legitimate address in the data was a secure site root starting with www and having no path. "
    f"Removing that prefix made the model flag every legitimate address, and rewriting phishing addresses in the legitimate format cut detection from {pc_(rel_orig)} to {pc_(rewrite_orig)}. "
    "A robustness gate now blocks such models, and a host-name model that replaced it "
    f"detected {pc_(HM['test']['recall'], 0)} of phishing addresses at a {pc_(HM['test']['false_positive_rate'])} false-alarm rate. "
    "No grocery fraud labels exist yet, and the paper sets out how to collect them."
)
KEYWORDS = "fraud detection; online grocery retail; mobile money; data leakage; probability calibration; phishing detection"

add("title", text=TITLE)
add("authors", lines=AUTHOR["author_lines"])
add("abstract", text=ABSTRACT)
add("keywords", text=KEYWORDS)

# ============================================================================================================ 1 Introduction
H1("1. Introduction")
H2("1.1 Background")
P("Mobile money has become the main way many people in sub-Saharan Africa move value. The GSMA counted more than two billion registered mobile money accounts worldwide in 2024, "
  "more than one billion of them in sub-Saharan Africa, and almost 1.7 trillion US dollars passing through those accounts during the year [[GSMA2025|pp. 3, 14]]. "
  "Online shops can reach these customers through payment aggregators that offer card and mobile money checkout, so a small grocery store can open with little more than a catalogue, "
  "a hosted checkout and a delivery service. The same report says that fraud remained a pervasive issue for the industry in 2024 and that most of it involves agents or customers [[GSMA2025|p. 63]].")
P("A grocery order differs from the transactions studied in most fraud research. The basket holds everyday items, the amounts are small, and the merchant sees only what the customer "
  "types at checkout and what the payment provider returns. The risk assessment in this study uses no device fingerprint, no network address or location, and no card numbers, "
  "which stay with the payment provider. Whatever assessment the store runs must work with the fields it has, and a member of staff must be able to explain a score to a customer who was flagged by mistake.")
H2("1.2 Problem statement")
P("Two problems follow. First, supervised models need labelled fraud, and a new store has none. Public datasets are the obvious substitute, but they describe other things: "
  "anonymised card transactions, simulated mobile money transfers and phishing web addresses. None carries the fields of a grocery order. Second, published performance on such "
  "datasets is hard to trust. A survey of machine-learning research found leakage of test information into training in 294 papers across 17 fields [[Kapoor2023]], and an analysis of "
  "card-fraud studies reproduces a recall of 99.9% with a deliberately flawed pipeline [[Hayat2025]]. A shop that adopts a model because a paper reports near-perfect scores may "
  "be adopting an artefact of the evaluation.")
H2("1.3 Research gap")
BUL([
    "Reviews of e-commerce fraud detection describe many classifiers and report a shortage of real datasets [[Mutemi2024]]. Mobile money research leans on simulators because real "
    "transaction logs are private [[LopezRojas2016;Azamuke2024]].",
    "Studies of operational card-fraud systems show that labels arrive late and only for cases someone investigated [[DP2018]]. When outcomes are observed only for the cases that "
    "received an action, models and decision makers are hard to compare fairly [[Lakkaraju2017]].",
    "Benchmark data can reward cues that do not carry over to real conditions [[Geirhos2020]], and published scores are often inflated by leakage [[Kapoor2023;Hayat2025]].",
    "The studies reviewed here do not combine, for a small retailer, a decision aid built from its own fields, a refusal to score inputs a model never saw, and a plan for "
    "gathering the labels that the first two leave missing.",
])
H2("1.4 Research objectives")
H3("General objective")
P("To design and evaluate an auditable framework that helps a small online grocery store decide which orders need human review, using only data the store records.")
H3("Specific objectives")
NUM([
    "Define the fields the store records at checkout as a versioned schema that excludes outcome information and personal identifiers.",
    "Implement a transparent rule engine and a guard that refuses to score inputs a model was not trained on.",
    "Prepare two public datasets and train baseline and tree-based models under a leakage-controlled protocol.",
    "Measure the uncertainty of the results and the effect of common evaluation shortcuts.",
    "Specify how analyst-verified outcomes become training labels and when a trained model may be promoted.",
])
H2("1.5 Research questions")
NUM([
    "Which fields can a grocery store use for risk assessment, and how can the assessment stay explainable to staff and customers?",
    "How well do logistic regression, random forests and gradient boosting detect card fraud and phishing addresses when the evaluation avoids leakage, and how uncertain are the estimates?",
    "How much do common evaluation shortcuts inflate reported scores?",
    "Can public datasets support a supervised model for grocery orders and, if not, what protocol will produce usable labels?",
    "Are the predicted probabilities calibrated, and which inputs drive the predictions?",
])
H2("1.6 Research contributions")
BUL([
    "A framework that joins a rule engine, a schema guard and per-order model records, with append-only analyst outcomes (Section 3.1).",
    "A leakage-controlled benchmark on two public datasets, with bootstrap intervals, paired tests and five repeated splits (Section 4).",
    "Measured inflation from evaluation shortcuts: oversampling before the split, keeping duplicate rows, and formatting artefacts in the web-address data (Sections 4.9 and 5).",
    "A robustness gate that refuses address models whose verdicts change with cosmetic edits, motivated by the failure of the first model we trained, and a weaker host-name model that passes it (Sections 3.1 and 4.9).",
    "A label-collection protocol with an audit sample of unflagged orders, readiness thresholds, shadow-mode deployment for experimental models and a promotion gate that requires "
    "a model to beat the rules (Section 3.1).",
    "An open implementation with automated tests and continuous integration (Section 4.10). The contribution is the framework and its evaluation; none of the classifiers is new.",
])

# ============================================================================================================ 2 Literature review
H1("2. Literature review")
H2("2.1 Existing methods")
P("Fraud detection has been reviewed many times. Recent reviews cover anomaly detection for financial fraud [[Hilal2022]] and machine learning for e-commerce fraud, where a "
  "systematic review of 101 publications reports a rising use of neural networks and a shortage of real datasets [[Mutemi2024]]. Practitioners have described what makes card fraud "
  "hard: class imbalance, change in behaviour over time and the delay before labels arrive. [[n:DP2018]] formalised these problems for a stream of more than 75 million transactions "
  "over three years and proposed a learning strategy for them. Hybrid designs add unsupervised outlier scores to a supervised classifier and report better detection [[Carcillo2021]]. "
  "In online marketplaces, supervised classifiers with custom preprocessing and imbalance handling can detect organised retail fraud from buyer and seller behaviour [[Mutemi2023]].")
P("Mobile money has its own literature, but real transaction logs are private, so researchers use simulators. PaySim generates mobile money transactions from an original dataset "
  "[[LopezRojas2016]], and MoMTSim is a multi-agent simulation calibrated for mobile money transactions whose synthetic data are compared with real data by statistical tests [[Azamuke2024]]. "
  "Simulated labels describe the simulator's assumptions about fraud, so they cannot confirm that a model finds fraud in a real store.")
P("Phishing detection from web addresses has a similar history. [[n:Sahingoz2019]] compared seven classifiers on language-based address features and reported 97.98% accuracy for a "
  "random forest. A review of 80 studies groups the techniques into list-based, visual-similarity, heuristic, machine-learning and deep-learning "
  "approaches [[Safi2023]]. [[n:Prasad2024]] released the dataset used here: 134,850 legitimate and 100,945 phishing addresses, with features drawn from the address and from the page.")
H2("2.2 AI and machine-learning approaches")
P("Tree ensembles remain strong on medium-sized tabular data, even against deep networks [[Grinsztajn2022]], and random forests [[Breiman2001]] are a common fraud baseline. "
  "Class imbalance is usually handled by resampling or by class weights. A study of balancing methods found that oversampling helps weak classifiers but not strong ones whose "
  "hyperparameters were tuned [[Elor2022]]. Rebalancing also distorts predicted probabilities, which matters when a threshold is meant to express a cost [[DP2015]]. "
  "Isotonic regression and Platt scaling repair the distortion; [[n:Niculescu2005]] found that boosted trees, random forests and support vector machines gave the best "
  "probabilities after calibration.")
P("For evaluation, precision-recall curves are more informative than ROC curves when positives are rare [[Saito2015]], and the Matthews correlation coefficient summarises all four cells "
  "of the confusion matrix [[Chicco2020]]. Leakage, meaning the use at training time of information that would not exist at prediction time, was described for data mining "
  "more than a decade ago [[Kaufman2012]]. In card-fraud research it takes the form of resampling or scaling before the split, vague reporting, weak temporal validation and "
  "thresholds tuned for recall [[Hayat2025]]. Shortcut learning describes models that succeed on a benchmark through cues that fail under real conditions [[Geirhos2020]].")
H2("2.3 Comparative analysis")
TAB("lit", "Comparison of related studies. Only figures stated in the cited sources are given.", ["Author", "Method", "Dataset", "Performance", "Limitations"], [
    ["[[n:DP2018]]", "Learning strategy for imbalance, drift and label delay", "Stream of more than 75 million card transactions over three years", "Realistic evaluation on a long stream; no single score quoted here", "Card transactions only; does not address retail checkout fields"],
    ["[[n:Carcillo2021]]", "Supervised classifier plus unsupervised outlier scores at several granularities", "Real annotated card data", "Detection accuracy improves over the supervised stage alone", "Supervised stage still needs labels"],
    ["[[n:Hayat2025]]", "Critical examination of card-fraud evaluation", "Card data of European cardholders", "A flawed pipeline reaches 99.9% recall", "Evaluation study; no deployable system"],
    ["[[n:LopezRojas2016]]", "PaySim agent-based simulator of mobile money", "Synthetic, based on an original private dataset", "Not applicable (simulator)", "Fraud labels come from the simulator's assumptions"],
    ["[[n:Azamuke2024]]", "MoMTSim multi-agent simulator calibrated to mobile money data", "Synthetic, calibrated against real mobile money data", "Synthetic and real data compared with Kolmogorov-Smirnov test, sum of squared errors and Bland-Altman plots", "Synthetic labels"],
    ["[[n:Sahingoz2019]]", "Seven classifiers on language-based URL features; random forest best", "Phishing and legitimate URLs described in the paper", "97.98% accuracy", "Address text only"],
    ["[[n:Prasad2024]]", "Framework with a URL similarity index and incremental learning", "PhiUSIIL: 134,850 legitimate and 100,945 phishing URLs", "Not quoted here", "Page-content features need the page to be fetched"],
    ["[[n:Emmanuel2026]] (preprint)", "Multi-layer perceptron on 16 URL structure features", "PhiUSIIL (235,795 URLs)", "99.24% accuracy, 98.74% precision, 99.95% recall, F1 99.34%, ROC-AUC 99.65%", "Preprint; split not stated in the abstract"],
    ["[[n:Mutemi2024]]", "Systematic review of machine learning for e-commerce fraud", "101 publications", "Not applicable (review)", "Reports few real datasets"],
    ["This study", "Rule engine, schema guard, leakage-controlled models, robustness gate, label protocol", "ULB card data; PhiUSIIL; scripted store checkouts", f"Card PR-AUC {f(RF['test']['pr_auc'])}; URL host-name model PR-AUC {f(HM['test']['pr_auc'])}", "No grocery fraud labels yet; weak URL model"],
], [1.2, 1.9, 1.7, 1.9, 1.6], size=15, leftAll=True, boldRows=[9])
H2("2.4 Research gap")
P("The studies above leave five gaps that matter to a small retailer. They are listed in {T:gap} together with the part of this study that responds to each.")
TAB("gap", "Research gaps and how this study responds.", ["Gap", "Evidence", "Response in this study"], [
    ["No labelled fraud data for a new store", "Shortage of real datasets [[Mutemi2024]]; reliance on simulation [[LopezRojas2016;Azamuke2024]]", "Rule engine from the store's own fields; label-collection protocol"],
    ["Public benchmarks lack a retailer's fields", "Card data holds anonymised components; PaySim holds account balances", "Versioned schema and a guard that returns unsupported_input_schema"],
    ["Inflated or leaky reported scores", "[[Kapoor2023;Hayat2025]]", "Leakage-controlled protocol; measured inflation from evaluation shortcuts"],
    ["Benchmark shortcuts", "[[Geirhos2020]]", "Feature ablation, perturbation tests and a robustness gate on the phishing data"],
    ["Biased labels from review", "[[Lakkaraju2017;DP2018]]", "Verified flag, audit sample of unflagged orders, rules baseline in the promotion gate"],
], [2.0, 3.0, 3.3], leftAll=True)

# ============================================================================================================ 3 Materials and methods
H1("3. Materials and methods")
H2("3.1 Proposed framework")
P("{F:arch} shows the system. A customer builds a cart and checks out through a React storefront. The FastAPI service creates the order and a payment attempt in one transaction, keyed "
  "by an idempotency header so that a repeated request returns the same order. The customer chooses card, MTN Mobile Money or Airtel Money, or cash on delivery, and the service asks the "
  "provider's hosted checkout page for the matching option. The service accepts an online payment only after asking the provider directly to verify the reference, currency and amount, "
  "and a background job re-checks pending payments every minute. We tested the provider integration against a fake provider server and made no real payment during this study.")
P("When the order is saved, the rule engine store_risk_v1 computes a score from twelve fields ({T:schema}) and stores the inputs and the reasons with the assessment. A score of 30 or "
  "more opens a case for a person to review, a score of 60 or more is labelled high, and four rules (high value, bulk quantity, order velocity and repeated rejections) open a case "
  "on their own. Nothing blocks the order or the payment. The same event is offered to the model service, which first validates the input against the versioned schema "
  "grocery_txn_v1. A missing, unexpected or malformed field produces the status unsupported_input_schema or invalid_input and no score is created. The research card model expects 30 "
  "inputs (Time, Amount and 28 anonymised components) that the store schema does not contain, so for every order it answers with the field names it could not find. A model trained on store data would run in shadow mode while it is "
  "marked experimental: its probability is stored beside the rule score and it cannot raise alerts.")
P("Staff can record an outcome for any order: confirmed fraud, false positive, legitimate or undetermined, with a flag that shows whether evidence outside the system verified it. Rows "
  "are only ever appended; the newest row for an order wins. Only verified, definite outcomes become labels, and unreviewed orders are not assumed legitimate. "
  "A deterministic weekly sample puts about one in ten unflagged orders in front of reviewers, so that labels are not drawn only from orders the rules already suspected "
  "[[Lakkaraju2017]]. Training is attempted only with at least 150 verified fraud cases, 1,000 verified legitimate cases and 50 customers. The validation gate then requires 30 "
  "fraud rows in a customer-grouped test set, a score well above a do-nothing baseline, a successful reload in a fresh process and a better score than the rule engine on the same "
  "held-out customers. A model trained on fewer than 1,000 verified fraud cases stays experimental. {F:flow} shows the protocol used for every model in this paper.")
FIG("arch", "fig01_architecture.png", "System architecture of the store and its risk-assessment services.")
FIG("flow", "fig02_workflow.png", "Training and evaluation protocol, with the controls against leakage.")
P("The address model has one more gate, added after the experiments in Section 4.9. On up to 4,000 held-out legitimate addresses it changes one cosmetic cue at a time (removing a leading www, switching to http, "
  "adding a trailing slash, adding a path), and it rewrites up to 4,000 held-out phishing addresses in the legitimate format. A model is refused if the flagged share of legitimate addresses rises by more than five percentage "
  "points after any change, or if it keeps less than 80% of its detections after the rewrite. Every address model is also saved as experimental, and the ScamWatch checker skips experimental models, "
  "so no verdict from one reaches a user.")

H2("3.2 Dataset description")
TAB("data", "Datasets used. No store data were used for training.", ["Dataset", "Source and licence", "Rows (raw, cleaned)", "Positive class", "Inputs used", "Split (seed 42)"], [
    ["Card transactions", "ULB Machine Learning Group and Worldline, OpenML mirror 1597; licence field \"Public\" [[DP2015]]", f"{n_(cb['cleaning']['raw_rows_in_file'])}; {n_(n_card_rows)}", f"{card_fraud} fraud ({pc_(card_fraud / n_card_rows, 3)})", "Time (as 24-hour cycle), Amount, V1 to V28", f"Stratified 80/20: train {n_(RF['split']['train_rows'])} ({RF['split']['train_class_counts']['fraud']} fraud), test {n_(RF['split']['test_rows'])} ({RF['split']['test_class_counts']['fraud']} fraud)"],
    ["Web addresses", "PhiUSIIL, UCI data set 967; CC BY 4.0 [[Prasad2024]]", f"{n_(pb['cleaning']['rows_before'])}; {n_(ph_rows)}", f"{n_(ph_pos)} phishing ({pc_(ph_pos / ph_rows)})", "31 features computed from the address text (10 host-name features for the replacement model)", f"Grouped by domain 80/20: train {n_(PLR['split']['train_rows'])}, test {n_(PLR['split']['test_rows'])} ({n_(PLR['split']['test_class_counts']['fraud'])} phishing)"],
    ["Store orders", "Scripted checkouts in a throw-away database (synthetic customers)", f"{N_SCEN} scenarios", "Not applicable", "12 schema fields ({T:schema})", "Not applicable"],
], [1.0, 2.1, 1.0, 1.1, 1.7, 2.3], size=15, leftAll=True)
P(f"The card data hold the transactions of European cardholders over two days in September 2013. The file has {n_(cb['cleaning']['raw_rows_in_file'])} rows with Time, Amount, 28 anonymised "
  f"principal components (V1 to V28) and the label Class. After removing {n_(cb['cleaning']['dropped_exact_duplicates'])} exact duplicate rows, {n_(n_card_rows)} rows remain, of which "
  f"{card_fraud} are fraud. A classifier that always answers \"legitimate\" would be right {pc_(cb['dummy']['accuracy'], 2)} of the time, which is why accuracy is not used to rank models.")
P(f"From the phishing data we took only the address text, the label and the registrable domain, which is the grouping key. After removing {pb['cleaning']['dropped_exact_duplicates']} "
  f"duplicate addresses, {n_(ph_rows)} rows remain. In the file, label 1 means legitimate; we inverted it so that 1 means phishing. Both datasets were downloaded in October 2026 "
  "with their licence terms accepted, and each file was checked against a SHA-256 checksum recorded at download.")
H2("3.3 Data pre-processing")
BUL([
    "Missing values: none occurred in either dataset. The pipeline would drop rows with missing or non-finite values and count them.",
    "Noise removal: exact duplicate rows (card data) and duplicate addresses (web data) were removed before the split, so that copies cannot sit on both sides.",
    "Normalisation: every input was standardised with the mean and variance of the training partition only, inside the pipeline.",
    "Encoding: the two public datasets have numeric inputs. The store schema has two categorical fields, encoded one-hot with fixed vocabularies.",
    "Data augmentation: none.",
    "Class balancing: class weights (balanced) instead of resampling, followed by probability calibration. We did not use SMOTE because balancing mainly helps weak classifiers [[Elor2022]] and because oversampling before the split is one of the leakage routes examined in Section 4.9.",
])
H2("3.4 Feature engineering")
P("For the card data, Amount was log-transformed. Time counts seconds from the first transaction of the file, so it identifies a position in the collection window instead of a property of a "
  "transaction; we converted it to a position in a 24-hour cycle (sine and cosine) and dropped the raw value. For the web addresses we built two feature sets. The first has 31 lexical features computed from the whole address "
  "string: lengths of the address, host, path and query; counts of dots, hyphens, underscores, at-signs, equals signs, question marks, ampersands, percent signs, digits and other "
  "special characters; digit and letter ratios; the number of subdomains; whether the host is an IP address or contains punycode; the entropy and longest label of the host; "
  "the length of the top-level domain and whether it is common; flags for the secure protocol, a non-standard port, a leading \"www\" and a double slash in the path; and a count of "
  "suspicious keywords. The second, built after the experiments in Section 4.9, has 10 features of the canonical host name only: its length, number of subdomains, digit ratio, hyphen count, entropy, longest label, "
  "top-level domain length and commonness, and flags for an IP address and for punycode. The canonical host ignores the scheme, a leading www, the port, the path, the query and any trailing slash. "
  "We excluded the dataset's page-content columns because they require fetching the page, which the checker never does; columns computed from dataset-wide statistics "
  "because they cannot be recomputed for one new address; and identifiers.")
P("The store schema ({T:schema}) holds only fields known when the order arrives. It excludes the payment outcome of the order, order and delivery status, the analyst verdict, names, "
  "contact details, address text, card data and customer identifiers. All twelve fields are used; no feature selection was applied.")
rows = []
for spec in store_schema.FEATURE_SPECS:
    allowed = spec["allowed"]
    if spec["kind"] == "category":
        al = ", ".join(allowed)
    elif spec["kind"] == "bool":
        al = "true or false"
    else:
        al = f"{allowed[0]:,} to {allowed[1]:,}"
    rows.append([spec["name"], spec["kind"], al] + [spec[k].replace("PAID", "paid").replace("NOT", "not") for k in ("source", "privacy")])
TAB("schema", f"Store feature schema {store_schema.SCHEMA_VERSION}. Currency must be ZMW; other currencies are refused.", ["Field", "Type", "Allowed values", "Source at checkout", "Privacy note"], rows,
    [1.8, 0.6, 1.3, 3.0, 2.6], size=14, leftAll=True)
H2("3.5 Models")
P("Four classifiers were compared on each public dataset: a dummy classifier that predicts the training prevalence; logistic regression with L2 penalty and balanced class weights; "
  "a random forest of 150 trees with balanced subsample weights [[Breiman2001]]; and histogram-based gradient boosting with balanced class weights. All were implemented in scikit-learn "
  "[[Pedregosa2011]]. We did not train deep networks: with 378 training frauds and 30 inputs, tree ensembles are a strong default for tabular data [[Grinsztajn2022]]. The "
  "scikit-learn gradient-boosting classifier belongs to the same family as XGBoost, LightGBM and CatBoost and needs no extra dependency.")
P("The rule engine is a set of nine named rules with fixed points ({T:rules}). The score is the sum of the points that fire, capped at 100, and every assessment stores the fields used and a plain-language reason "
  "for each rule. The limits are deployment parameters; the defaults are a high-value limit of ZMW 5,000, a bulk quantity of 15, four orders per hour and five rejected checkouts in ten minutes.")
TAB("rules", "Rules of store_risk_v1. A hard rule opens a case even when the total score is below 30.", ["Rule", "Condition", "Points", "Hard"], [
    ["high_value", "Order total at or above the high-value limit", "30", "yes"],
    ["bulk_quantity", "A line quantity at or above the bulk limit (15)", "15", "yes"],
    ["order_velocity", "Four or more orders by the customer within an hour", "20", "yes"],
    ["repeated_rejections", "Five or more rejected checkouts in ten minutes", "20", "yes"],
    ["first_order_large", "No earlier paid order and a total of at least half the high-value limit", "15", "no"],
    ["spend_spike", "At least two earlier paid orders, a total of at least four times their average, and at least ZMW 100", "20", "no"],
    ["failed_payments", "Three or more failed payments in 24 hours (two failures score 10)", "25", "no"],
    ["new_address", "Delivery to an address the customer has not used, for a customer with earlier orders", "10", "no"],
    ["night_order", "Order placed between 00:00 and 05:00 local time", "5", "no"],
], [1.6, 5.2, 0.7, 0.6], leftAll=True)
H2("3.6 Model optimisation")
P("Hyperparameters were chosen by four-fold stratified cross-validation on the training partition, with average precision (PR-AUC) as the criterion; {T:hyper} lists the grids and the selected values. "
  "The chosen model's out-of-fold predictions were used twice: to fit an isotonic regression that turns scores into probabilities [[Niculescu2005]], and to choose the decision threshold. For the card and "
  "first web-address models the threshold maximises the F2 score, which weights recall twice as heavily as precision because a missed fraud costs more than an unnecessary review. "
  "For the host-name model, which may only raise suspicion, the threshold gives the highest recall at a false-positive rate of at most 1%. The test partition played no part in either step. The inner cross-validation for the "
  "web addresses was stratified, not grouped by domain, so its scores are optimistic; the outer test partition is grouped and its results are the ones reported.")
def fmt_params(p):
    return ", ".join(f"{k} = {'none' if v is None else v}" for k, v in p.items())


hy_rows = []
for fam in FAM:
    for g in CM[fam]["cv_grid"]:
        sel = "yes" if g["params"] == CM[fam]["selected"]["params"] else ""
        hy_rows.append([CM[fam]["label"], fmt_params(g["params"]), f(g["cv_pr_auc"]), sel])
TAB("hyper", "Hyperparameter grid and cross-validated PR-AUC for the card data (training partition, four folds).", ["Model", "Settings", "CV PR-AUC", "Selected"], hy_rows, [2.4, 4.2, 1.0, 0.8], leftAll=True,
    note="Note. Random forests used 150 trees. The web-address models used the same grids for logistic regression and gradient boosting and one random-forest setting (minimum leaf size 2).")
H2("3.7 Explainability")
P("The rule engine explains itself: each assessment lists the rules that fired and their points. For the trained models we used permutation importance, which measures how much PR-AUC falls when one input "
  "is shuffled. It was computed on held-out rows with five repeats: all 95 test frauds plus 8,000 legitimate rows for the card data, and 8,000 random rows for the web addresses. For the web-address logistic "
  "model we also read the standardised coefficients. We did not use SHAP because permutation importance answers the question asked here, which inputs the held-out score depends on, at a fraction of the cost.")
H2("3.8 Experimental setup")
env = cb["environment"]
P(f"Experiments ran in Python {env['python']} with scikit-learn {env['scikit-learn']}, pandas {env['pandas']}, NumPy {env['numpy']} and SciPy {env['scipy']} on Windows 11 with {env['cpu_count']} logical processors "
  "and 8 GB of memory. All random seeds are fixed (42 for the main split; 11, 22, 33, 44 and 55 for the repeated splits). The software, the experiment scripts and the saved results are in a public repository "
  "(release tag paper-v1). The application is also tested on Linux with Python 3.12 and PostgreSQL 16 in continuous integration (Section 4.10).")
H2("3.9 Evaluation metrics")
P("For each model we report accuracy, precision, recall, specificity, F1, the Matthews correlation coefficient [[Chicco2020]], the area under the ROC curve, and the area under the precision-recall curve "
  "(average precision), which is the primary metric [[Saito2015]]. Precision, recall and F1 use the threshold chosen on training data. Calibration is measured by the Brier score and by the "
  "expected calibration error in ten equal-count bins. Uncertainty is shown by 95% percentile intervals from a stratified bootstrap of 1,000 resamples that keeps the class counts fixed "
  "[[Efron1979;Boyd2013]]. Models are compared with a paired bootstrap of the same resamples and with the exact McNemar test on the rows where two classifiers disagree [[Dietterich1998]]. "
  "Variation caused by the split is measured with five further random splits.")

# ============================================================================================================ 4 Results
H1("4. Experimental results")
H2("4.1 Dataset analysis")
FIG("data", "fig03_datasets.png", "Class balance of the two public datasets (a, b) and the collection artefact in the web-address data (c).", width=6.4)
P(f"{{F:data}} shows the two class balances. Fraud is {pc_(card_fraud / n_card_rows, 3)} of the card transactions, while phishing is {pc_(ph_pos / ph_rows)} of the web addresses. "
  f"Panel (c) shows a property of the web data that the later results depend on. All {n_(pc['counts']['all rows']['legitimate'])} legitimate addresses have the form https://www.domain: "
  f"{pc_(sh['HTTPS']['legitimate'], 0)} use the secure protocol, {pc_(sh['www prefix']['legitimate'], 0)} start with www, and {pc_(sh['no trailing slash or path']['legitimate'], 0)} have no path, query or trailing slash. "
  f"Among phishing addresses the shares are {pc_(sh['HTTPS']['phishing'])}, {pc_(sh['www prefix']['phishing'])} and {pc_(sh['no trailing slash or path']['phishing'])}, and only {pc_(sh[TEMPLATE]['phishing'])} "
  f"({n_(pc['counts'][TEMPLATE]['phishing'])} of {n_(pc['counts']['all rows']['phishing'])}) match the legitimate format in all three respects. "
  f"The mean address length is {pc['mean_url_length']['legitimate']:.0f} characters for legitimate and {pc['mean_url_length']['phishing']:.0f} for phishing.")
H2("4.2 Model performance")
bc, bp = cb["bootstrap"], pb["bootstrap"]


def perf_rows(models, dummy, boot):
    rows = [["Dummy (training prior)", f(dummy["accuracy"], 4), "0.000", "0.000", "0.000", "0.000", "0.500", f(dummy["pr_auc"], 4)]]
    for fam in FAM:
        t = models[fam]["test"]
        rows.append([models[fam]["label"], f(t["accuracy"], 4), f(t["precision"]), f(t["recall"]), f(t["f1"]), f(t["mcc"]), f(t["roc_auc"]), f"{f(t['pr_auc'])} {band_br(boot, fam, 'pr_auc')}"])
    return rows


hdr = ["Model", "Accuracy", "Precision", "Recall", "F1-score", "MCC", "ROC-AUC", "PR-AUC [95% CI]"]
w8 = [2.2, 0.9, 0.9, 0.8, 0.8, 0.8, 0.9, 1.9]
best_row = lambda models: 1 + FAM.index(max(FAM, key=lambda k: models[k]["test"]["pr_auc"]))     # noqa: E731  (row 0 is the dummy classifier)
TAB("card", f"Card fraud: held-out performance ({n_(RF['split']['test_rows'])} transactions, {RF['split']['test_class_counts']['fraud']} fraud).", hdr, perf_rows(CM, cb["dummy"], bc), w8,
    note="Note. Precision, recall, F1 and MCC at each model's own threshold, chosen on out-of-fold training predictions. Bold marks the highest PR-AUC.", boldRows=[best_row(CM)])
TAB("phish", f"Web addresses, original 31-feature models: held-out performance ({n_(PLR['split']['test_rows'])} addresses, {n_(PLR['split']['test_class_counts']['fraud'])} phishing, domains kept apart).", hdr, perf_rows(PM, pb["dummy"], bp), w8,
    note="Note. Thresholds chosen on out-of-fold training predictions. Bold marks the highest PR-AUC. Section 4.9 shows that these scores mostly reflect how the addresses were formatted.", boldRows=[best_row(PM)])
d_rf_lr = paired(bc, "logistic_regression", "random_forest")
d_rf_hg = paired(bc, "random_forest", "hist_gradient_boosting")
d_lr_hg = paired(bc, "logistic_regression", "hist_gradient_boosting")
mc = cb["mcnemar"]                       # "a vs b": a_right_b_wrong counts rows that model a classifies correctly and model b does not
m_lr_rf, m_lr_hg, m_rf_hg = mc["logistic_regression vs random_forest"], mc["logistic_regression vs hist_gradient_boosting"], mc["random_forest vs hist_gradient_boosting"]
fp_ = {fam: CM[fam]["test"]["confusion_matrix"]["fp"] for fam in FAM}
bonf = 0.05 / len(mc)
assert max(m["p_value"] for m in mc.values()) < bonf, "the text claims that every McNemar comparison survives a Bonferroni correction"
P(f"On the card data the random forest has the highest PR-AUC ({f(RF['test']['pr_auc'])}). The paired bootstrap puts its advantage over logistic regression at {f(-d_rf_lr['mean'])} "
  f"(95% interval {f(-d_rf_lr['hi'])} to {f(-d_rf_lr['lo'])}) and over gradient boosting at {f(d_rf_hg['mean'])} ({f(d_rf_hg['lo'])} to {f(d_rf_hg['hi'])}); both intervals exclude zero. By PR-AUC, logistic regression and gradient boosting "
  f"cannot be separated (difference {f(d_lr_hg['mean'])}, interval {f(d_lr_hg['lo'])} to {f(d_lr_hg['hi'])}). "
  f"The random forest also has the best precision ({f(RF['test']['precision'])}, interval {band(bc, 'random_forest', 'precision')}). Its recall is {f(RF['test']['recall'])} (interval {band(bc, 'random_forest', 'recall')}), against "
  + (f"{f(LR['test']['recall'])} for both other models" if abs(LR["test"]["recall"] - HG["test"]["recall"]) < 5e-4 else f"{f(LR['test']['recall'])} for logistic regression and {f(HG['test']['recall'])} for gradient boosting")
  + f". The wide intervals come from the {RF['split']['test_class_counts']['fraud']} fraud rows in the test partition: a single missed fraud moves recall by about one percentage point.")
rev_rf = "and the reverse never happens" if m_lr_rf["a_right_b_wrong"] == 0 else f"and wrong where logistic regression is right on {m_lr_rf['a_right_b_wrong']}"
P(f"The exact McNemar test compares the decisions that each model makes at its own threshold. The random forest is right where logistic regression is wrong on {m_lr_rf['b_right_a_wrong']} test rows, "
  f"{rev_rf} ({pval(m_lr_rf['p_value'])}). Against gradient boosting the counts are {m_rf_hg['a_right_b_wrong']} rows in the forest's favour and {m_rf_hg['b_right_a_wrong']} in the other's ({pval(m_rf_hg['p_value'])}). "
  f"Unlike PR-AUC, this test also separates logistic regression from gradient boosting: logistic regression is right where gradient boosting is wrong on {m_lr_hg['a_right_b_wrong']} rows, and the reverse holds on {m_lr_hg['b_right_a_wrong']} ({pval(m_lr_hg['p_value'])}). "
  f"Gradient boosting raises more false alarms ({fp_['hist_gradient_boosting']}, against {fp_['logistic_regression']} for logistic regression and {fp_['random_forest']} for the random forest). "
  f"All three p values stay below {bonf:.3f}, the Bonferroni threshold for three comparisons.")
rk = crk["models"]
P(f"The ROC-AUC ranks the models in the opposite order: gradient boosting {f(HG['test']['roc_auc'])}, logistic regression {f(LR['test']['roc_auc'])}, random forest {f(RF['test']['roc_auc'])}. "
  f"Calibration is not the cause: the raw forest score has the same ROC-AUC ({f(ce['raw_score']['roc_auc'])}) and a PR-AUC of {f(ce['raw_score']['pr_auc'])}; calibration lowers PR-AUC slightly because it reduces the "
  f"score to {ce['calibrated']['distinct_values']} distinct values. The cause is where the missed frauds land. The forest ranks {rk['random_forest']['frauds_above_99_9pct_of_legit']} of the {crk['fraud_rows']} test frauds above 99.9% of "
  f"legitimate transactions, against {rk['logistic_regression']['frauds_above_99_9pct_of_legit']} for logistic regression and {rk['hist_gradient_boosting']['frauds_above_99_9pct_of_legit']} for gradient boosting, "
  f"but {rk['random_forest']['frauds_below_median_legit']} of its frauds fall below the median legitimate transaction ({rk['logistic_regression']['frauds_below_median_legit']} and {rk['hist_gradient_boosting']['frauds_below_median_legit']} for the other two). "
  "ROC-AUC penalises those low-ranked frauds heavily, whereas PR-AUC rewards the top of the list, which is where an analyst works [[Saito2015]]. We therefore rank models by PR-AUC.")
FIG("cmp", "fig13_comparison.png", f"PR-AUC with 95% bootstrap intervals for the three classifiers. The no-skill baselines (the class prevalences, {f(cb['dummy']['pr_auc'], 4)} for cards and {f(pb['dummy']['pr_auc'], 2)} for web addresses) lie outside the plotted ranges.", width=6.2)
pr_web = [PLR["test"]["pr_auc"], PRF["test"]["pr_auc"], PHG["test"]["pr_auc"]]
gap_lr = max(pr_web) - PLR["test"]["pr_auc"]
P(f"On the web addresses all three original models reach a PR-AUC of at least {f(min(pr_web))}, and the largest difference between them is {max(pr_web) - min(pr_web):.4f}. "
  f"The simplest model, logistic regression, " + ("ties for the best score" if gap_lr < 5e-5 else f"scores {gap_lr:.4f} below the best") + f" ({f(PLR['test']['pr_auc'])}, interval {band(bp, 'logistic_regression', 'pr_auc')}). Section 4.9 shows why these scores should not be read as accuracy on real links.")
cal_rows = []
for tag, models in (("Card", CM), ("Web addresses", PM)):
    for fam in FAM:
        c = models[fam]["calibration"]
        cal_rows.append([tag, models[fam]["label"], f(c["brier_raw"], 5), f(c["brier_calibrated"], 5), f(c["ece_raw"], 5), f(c["ece_calibrated"], 5)])
TAB("calib", "Calibration on the held-out partition, before and after isotonic calibration.", ["Data", "Model", "Brier (raw)", "Brier (calibrated)", "ECE (raw)", "ECE (calibrated)"], cal_rows,
    [1.2, 2.2, 1.0, 1.3, 1.0, 1.3], note="Note. ECE is the expected calibration error in ten equal-count bins; lower is better.")
P("Class weights shift a classifier's scores away from true probabilities. On the card data, isotonic calibration cuts the Brier score of logistic regression from "
  f"{f(LR['calibration']['brier_raw'], 4)} to {f(LR['calibration']['brier_calibrated'], 5)}, and its expected calibration error from {f(LR['calibration']['ece_raw'], 4)} to {f(LR['calibration']['ece_calibrated'], 5)}. "
  f"The random forest was already close to calibrated (expected calibration error {f(RF['calibration']['ece_raw'], 5)} before and {f(RF['calibration']['ece_calibrated'], 5)} after). {{F:rel}} shows the reliability of the two selected models. "
  f"For the original web-address model the middle of the diagram is poor, but {pc_(pss['models']['logistic_regression']['share_below_0_05_or_above_0_95'])} of the held-out addresses score below 0.05 or above 0.95 and only "
  f"{pc_(pss['models']['logistic_regression']['share_between_0_2_and_0_8'], 2)} fall between 0.2 and 0.8, so the expected calibration error stays small.")
FIG("rel", "fig07_reliability.png", "Reliability of the calibrated scores on the held-out partitions. Bars show 95% Wilson intervals; bins with fewer than 15 rows are omitted.", width=6.0)
H2("4.3 Confusion matrix")
FIG("cm", "fig04_confusion.png", "Confusion matrices at the chosen thresholds. Percentages are row shares.", width=5.8)
ct, pt = RF["test"], PLR["test"]
flag_share = (ct["confusion_matrix"]["fp"] + ct["confusion_matrix"]["tp"]) / ct["test_rows"]
P(f"On the card data the random forest flags {ct['confusion_matrix']['tp'] + ct['confusion_matrix']['fp']} of {n_(ct['test_rows'])} transactions ({flag_share * 1000:.1f} per 1,000). "
  f"Of these, {ct['confusion_matrix']['tp']} are fraud and {ct['confusion_matrix']['fp']} are not, so {pc_(ct['precision'])} of the alerts are real. The {ct['confusion_matrix']['fn']} missed frauds are "
  f"{pc_(ct['false_negative_rate'])} of all frauds, and {pc_(ct['false_positive_rate'], 3)} of legitimate transactions are flagged. On the web addresses the original logistic model makes "
  f"{pt['confusion_matrix']['fp']} false alarms and {pt['confusion_matrix']['fn']} misses in {n_(pt['test_rows'])} addresses.")
H2("4.4 ROC curve")
FIG("roc", "fig05_roc.png", "ROC curves on the held-out partitions (axes truncated to show the region where the curves differ).", width=6.2)
H2("4.5 Precision-recall curve")
FIG("pr", "fig06_pr.png", "Precision-recall curves on the held-out partitions. The dashed line is the prevalence.", width=6.2)
p9 = {fam: rk[fam]["max_recall_at_precision_0_9"] for fam in FAM}
if p9["logistic_regression"] == 0 and p9["hist_gradient_boosting"] == 0:
    p9_text = f"The random forest keeps precision at or above 0.9 up to a recall of {f(p9['random_forest'], 2)}; neither of the other two models reaches a precision of 0.9 at any threshold."
else:
    p9_text = ("The recall at which precision stays at or above 0.9 is " + f"{f(p9['logistic_regression'], 2)} for logistic regression, {f(p9['random_forest'], 2)} for the random forest and {f(p9['hist_gradient_boosting'], 2)} for gradient boosting.")
P(f"The precision-recall curve for the card data shows the trade-off an analyst faces. {p9_text} At a precision of 0.5 the three models reach recalls of {f(rk['logistic_regression']['max_recall_at_precision_0_5'], 2)} (logistic regression), "
  f"{f(rk['random_forest']['max_recall_at_precision_0_5'], 2)} (random forest) and {f(rk['hist_gradient_boosting']['max_recall_at_precision_0_5'], 2)} (gradient boosting). "
  "The operating points marked on each curve come from thresholds that were fixed before the test partition was scored.")
H2("4.6 Training and validation curves")
FIG("curve", "fig09_curves_seeds.png", "Learning curve of the random forest on the training partition (a) and held-out PR-AUC on five random splits (b).", width=6.2)
sr, sl_ = cs["models"]["random_forest"]["summary"], cs["models"]["logistic_regression"]["summary"]
lc = cl
i_plateau = 2
FOLDS = {3: "three", 4: "four", 5: "five"}.get(lc["cv_folds"], str(lc["cv_folds"]))
P(f"The learning curve in {{F:curve}}a shows a training PR-AUC between {f(min(lc['train_pr_auc_mean']), 3)} and {f(max(lc['train_pr_auc_mean']), 3)} at every size. The cross-validated PR-AUC ({FOLDS} folds) rises from "
  f"{f(lc['validation_pr_auc_mean'][0], 3)} with {n_(lc['train_sizes'][0])} training rows to {f(lc['validation_pr_auc_mean'][i_plateau], 3)} with {n_(lc['train_sizes'][i_plateau])} rows (about "
  f"{round(lc['train_sizes'][i_plateau] * RF['split']['train_class_counts']['fraud'] / RF['split']['train_rows'])} frauds), then stays between {f(min(lc['validation_pr_auc_mean'][i_plateau:]), 3)} and "
  f"{f(max(lc['validation_pr_auc_mean'][i_plateau:]), 3)} up to {n_(lc['train_sizes'][-1])} rows. The standard deviation across folds is about {f(max(lc['validation_pr_auc_sd']), 2)}, so the later differences are within noise "
  "and more rows of the same kind would add little. The gap between the training and validation curves is expected for a random forest, whose trees fit the training rows almost perfectly; the validation curve is the one to read. "
  "Panel (b) shows how much a single split can mislead. Across five random splits the held-out PR-AUC of the "
  f"random forest averages {f(sr['pr_auc']['mean'])} with a standard deviation of {f(sr['pr_auc']['sd'])} and a range of {f(sr['pr_auc']['min'])} to {f(sr['pr_auc']['max'])}; for logistic regression the mean is "
  f"{f(sl_['pr_auc']['mean'])} (standard deviation {f(sl_['pr_auc']['sd'])}). The random forest is ahead on average in these splits, and the main split ({f(RF['test']['pr_auc'])}) falls below their mean.")
seed_rows = []
for fam in ("logistic_regression", "random_forest"):
    s = cs["models"][fam]["summary"]
    seed_rows.append([cs["models"][fam]["label"]] + [f"{f(s[k]['mean'])} ({f(s[k]['sd'])})" for k in ("pr_auc", "roc_auc", "precision", "recall", "f1")])
TAB("seeds", "Mean (standard deviation) over five random 80/20 splits of the card data.", ["Model", "PR-AUC", "ROC-AUC", "Precision", "Recall", "F1-score"], seed_rows, [2.4, 1.2, 1.2, 1.2, 1.2, 1.2])
chron = {fam: CM[fam]["chronological"] for fam in FAM}
best_chron = max(chron, key=lambda k: chron[k]["pr_auc"])
P(f"A chronological check trains on the oldest 80% of the transactions and tests on the newest 20% ({chron['random_forest']['fraud_in_test']} frauds). PR-AUC is "
  f"{f(chron['random_forest']['pr_auc'])} for the random forest, {f(chron['logistic_regression']['pr_auc'])} for logistic regression and {f(chron['hist_gradient_boosting']['pr_auc'])} for gradient boosting, "
  + ("so the random forest also comes first when the split follows time. " if best_chron == "random_forest" else f"so {CM[best_chron]['label'].lower()} comes first when the split follows time, unlike the random split. ")
  + "Precision and recall are omitted for this check because the threshold of the main split does not carry over to a different training set.")
H2("4.7 Feature importance")
FIG("imp", "fig08_importance.png", "Permutation importance on held-out data (mean drop in PR-AUC; bars show standard deviation over five repeats).", width=6.2)
cp_top = ci_["permutation"][:4]
pp_top = pi["permutation"][:4]
im_top = [x["feature"] for x in ci_["impurity"][:3]]
shared = [x["feature"] for x in cp_top if x["feature"] in im_top]
coef_top = [c["feature"] for c in sorted(pi["coefficients"], key=lambda c: -abs(c["standardised_coefficient"]))[:3]]
cue_names = [x["feature"] for x in pp_top[:3]]
coef_by = {c["feature"]: c["standardised_coefficient"] for c in pi["coefficients"]}
share_text = (f"so the two measures share only {shared[0]} among their leading features" if len(shared) == 1 else
              f"so only {', '.join(shared)} appear in both lists" if shared else "so the two measures name different leading features")
coef_text = (f"The standardised coefficients of the same model rank those three first as well ({', '.join(f'{c} {coef_by[c]:+.2f}'.replace('-', MINUS) for c in coef_top)}), with the signs that the data imply: "
             "a deeper path raises the phishing score, and a secure protocol or a www prefix lowers it. ") if set(coef_top) == set(cue_names) else ""
assert not coef_text or (coef_by["path_depth"] > 0 and coef_by["is_https"] < 0 and coef_by["has_www"] < 0), "the sign statement in the coefficient sentence no longer matches the results"
P("For the card data, shuffling " + ", ".join(f"{x['feature']} (PR-AUC drop {f(x['mean_drop_in_pr_auc'])})" if i == 0 else f"{x['feature']} ({f(x['mean_drop_in_pr_auc'])})" for i, x in enumerate(cp_top[:3]))
  + f" or {cp_top[3]['feature']} ({f(cp_top[3]['mean_drop_in_pr_auc'])}) hurts the random forest most. "
  f"The forest's own impurity-based importance puts {', '.join(im_top[:2])} and {im_top[2]} first, {share_text}. "
  "The components are anonymised, so the ranking shows which components carry signal but not what they mean. For the original web-address model the largest drops come from "
  + ", ".join(f"{x['feature']} ({f(x['mean_drop_in_pr_auc'])})" for x in pp_top[:3]) + f" and {pp_top[3]['feature']} ({f(pp_top[3]['mean_drop_in_pr_auc'])}). "
  "The top three are formatting cues, the ones examined in Section 4.9. " + coef_text)
H2("4.8 Explainability results")
P(f"{{T:scen}} and {{F:scen}} show {NUM_WORD.get(N_SCEN, str(N_SCEN))} scripted checkouts that between them make all nine rules fire. Each starts from a fresh customer, with earlier orders dated three days back unless the scenario is about recent behaviour. "
  "The limit for a high-value order was set to ZMW 300 so that basket sizes in the demonstration catalogue can reach it.")
TAB("scen", "Rule-engine behaviour on scripted checkouts.", ["Scenario", "Rules that fired", "Score", "Decision", "Case"], [
    [s["name"], ", ".join(r["rule"].replace("_", " ") for r in s["rules"]) or "none", str(s["score"]), s["decision"], "yes" if s["case_opened"] else "no"] for s in ss["scenarios"]], [2.6, 3.4, 0.7, 0.9, 0.7], leftAll=True,
    note="Note. A score of 30 or more is review and 60 or more is high. An order burst and repeated rejections open a case through hard rules, although each scores only 20.")
FIG("scen", "fig12_scenarios.png", "Rule points by scenario. Dashed lines mark the review and high bands.", width=6.2)
P("Weak signals do not escalate on their own: a spend spike, a new delivery address, a night-time order or three failed payments each score 25 points or fewer and open no case. "
  "A strong or combined pattern does escalate, as in the bulk first order (60) and the combined case (80). An order burst and repeated rejected checkouts each score only 20 but open a case, because their rules are hard rules. "
  "One result may surprise a reader: three failed payments in a day score 25 and do not reach review. A store that wants them to count can raise that rule's points, and the stored reasons make the change easy to justify.")
H2("4.9 Comparison with existing methods")
P("Direct comparison with published numbers is limited by differences in features, splits and thresholds. We therefore compare in three ways. {T:protocol} and {F:protocol} reproduce, on the same card data, "
  "evaluation shortcuts of the kind that [[n:Hayat2025]] describe. {T:shortcut}, {T:perturb} and {F:short} examine what the web-address scores depend on. {T:hostmodel} and {T:comp} then compare models with each other and with published results.")
prot_rows = []
for r in cp["rows"]:
    prot_rows.append([r["variant"].replace("(x20)", "(×20)"), f(r["pr_auc"]), f(r["roc_auc"]), f(r["precision"]), f(r["recall"]), f(r["f1"]), f"{r['test_fraud']:,}"])
TAB("protocol", "Effect of evaluation shortcuts on the same random forest (card data, threshold 0.5 on the raw score).", ["Protocol", "PR-AUC", "ROC-AUC", "Precision", "Recall", "F1", "Fraud rows in test"], prot_rows,
    [3.4, 0.8, 0.8, 0.9, 0.8, 0.7, 1.1], leftAll=False, note="Note. Rows A to C use the same model settings; only the protocol changes.")
FIG("protocol", "fig10_protocol.png", "Held-out scores of the same random forest under three protocols.", width=5.8)
P(f"Oversampling the fraud class twenty-fold before the split gives a PR-AUC of {f(protoB['pr_auc'], 2)} and an F1 of {f(protoB['f1'], 2)}, because copies of each training fraud sit in the test partition. "
  f"The correct protocol gives {f(protoA['pr_auc'])} and {f(protoA['f1'])}. Keeping the {n_(cb['cleaning']['dropped_exact_duplicates'])} duplicate rows is a smaller mistake but still raises PR-AUC from {f(protoA['pr_auc'])} to "
  f"{f(protoC['pr_auc'])}, since a duplicate of a training row often lands in the test partition. Choosing the threshold on the test partition lifts F1 from {f(protoA['f1'])} to "
  f"{f(protoA['best_threshold_on_test']['f1'])}. The same model, data and code give a score anywhere from {f(protoA['pr_auc'], 2)} to {f(protoB['pr_auc'], 2)} depending on the evaluation, the pattern that [[n:Kapoor2023]] and [[n:Hayat2025]] warn about.")
ab_rows = [[r["features"], str(r["n_features"]), f(r["pr_auc"]), f(r["roc_auc"]), f(r["f1"]), f(r["recall"])] for r in pa["rows"]]
TAB("shortcut", "Web addresses: logistic regression with different feature sets (domain-grouped test partition, threshold 0.5).", ["Feature set", "Features", "PR-AUC", "ROC-AUC", "F1", "Recall"], ab_rows,
    [4.0, 0.8, 0.8, 0.8, 0.7, 0.8], leftAll=False)
ab = {r["features"]: r for r in pa["rows"]}
single, wwwonly, three = ab["is_https only"], ab["has_www only"], ab["Three collection cues (is_https, has_www, path_depth)"]
P(f"The web-address score depends on how the addresses are written. The secure-protocol flag alone gives a PR-AUC of {f(single['pr_auc'])} (precision {f(single['precision'])}, recall {f(single['recall'])}: every legitimate address uses the "
  f"protocol, so any address that does not is phishing), the www flag alone gives {f(wwwonly['pr_auc'])}, and protocol plus address length gives {f(ab['is_https + URL length']['pr_auc'])}. Three formatting cues (protocol, www and path depth) "
  f"give {f(three['pr_auc'])}, almost the {f(ab['All 31 URL-text features']['pr_auc'])} of all 31 features. The host-name features alone give {f(ab['Host-name features only']['pr_auc'])}.")
perturb_rows = []
cos = [("legitimate", "as released", "Legitimate addresses, as released"), ("legitimate", "remove the www prefix", "Legitimate: remove the www prefix"), ("legitimate", "use http instead of https", "Legitimate: use http"),
       ("legitimate", "add a trailing slash", "Legitimate: add a trailing slash"), ("legitimate", "add a path", "Legitimate: add a path"),
       ("phishing", "as released", "Phishing addresses, as released"), ("phishing", "add a www prefix", "Phishing: add a www prefix"), ("phishing", "use https instead of http", "Phishing: use https"),
       ("phishing", "drop a lone trailing slash", "Phishing: drop a lone trailing slash"), ("phishing", "rewrite as https://www.<host> (legitimate template)", "Phishing: rewrite as https://www.host")]
host_sh = HM["cosmetic_flagged_shares"]
for side, key, label in cos:
    orig = ppt[side][key]["flagged_share"]
    hkey = "rewrite as https://www.<host>" if key.startswith("rewrite") else key
    hv = host_sh[side].get(hkey, host_sh[side]["as released"])           # features of the host-name model ignore the other changes, so the share cannot move
    perturb_rows.append([label, pc_(orig), pc_(hv)])
TAB("perturb", "Share of held-out addresses flagged after one cosmetic change.", ["Change applied to the held-out addresses", "Original model (31 features)", "Host-name model (10 features)"], perturb_rows, [4.6, 2.2, 2.2],
    note=f"Note. {n_(ppt['legitimate']['as released']['n'])} legitimate and {n_(ppt['phishing']['as released']['n'])} phishing addresses. The host-name model ignores the scheme, www, path and trailing slash by construction, so only changes that alter the host can move its output.")
legit_after = {k: ppt["legitimate"][k]["flagged_share"] for k in ("remove the www prefix", "use http instead of https", "add a trailing slash", "add a path")}
if min(legit_after.values()) >= 0.9995:
    legit_text = "but every one of them (100%) after any single change: removing www, switching to http, adding a trailing slash or adding a path. "
else:
    legit_text = (f"but {pc_(legit_after['remove the www prefix'], 1)} after removing www, {pc_(legit_after['use http instead of https'], 1)} after switching to http, "
                  f"{pc_(legit_after['add a trailing slash'], 1)} after adding a trailing slash and {pc_(legit_after['add a path'], 1)} after adding a path. ")
P(f"{{T:perturb}} and {{F:short}}(b) change one cue at a time. The original model flags {pc_(ppt['legitimate']['as released']['flagged_share'])} of the legitimate test addresses as released, " + legit_text +
  f"It detects {pc_(rel_orig)} of phishing addresses as released and {pc_(rewrite_orig)} after they are rewritten as https://www.host. Restricted to addresses that already match the legitimate format, "
  f"its PR-AUC falls to {f(sub_t['production_model']['pr_auc'])} (precision {f(sub_t['production_model']['precision'])}, recall {f(sub_t['production_model']['recall'])}) on the {sub_t['test_phishing']} phishing addresses of the test partition.")
sp_rows = psp["rows"]
sp_ordinary = [r for r in sp_rows if r["kind"] == "legitimate-looking"]
sp_phish = [r for r in sp_rows if r["kind"] == "phishing in the data"]
sp_rewritten = [r for r in sp_rows if r["kind"] == "same host, legitimate format"]
sp_by = {r["url"]: r for r in sp_rows}
assert {r["url"] for r in sp_ordinary if not r["original_flagged"]} == {"https://www.example.co.zm"}, "the spot-check sentence names the one ordinary address that passes"
sp_pass = [r for r in sp_rewritten if not r["original_flagged"]]
P(f"Spot checks on a fixed list of {len(sp_rows)} addresses agree. The original model flagged {sum(r['original_flagged'] for r in sp_ordinary)} of {len(sp_ordinary)} ordinary addresses (google.com, a Gmail path, a GitHub repository page and example.co.zm) "
  f"and passed only www.example.co.zm. It flagged all {sum(r['original_flagged'] for r in sp_phish)} phishing addresses taken from the data, but passed {len(sp_pass)} of those {len(sp_rewritten)} hosts once they were rewritten as https://www.host. "
  f"For sparkasse-auth.com the score was {f(sp_by['https://sparkasse-auth.com/']['original_probability'], 2)} as released and {f(sp_by['https://www.sparkasse-auth.com']['original_probability'], 3)} after the rewrite, against a threshold of {f(psp['original_threshold'], 2)}. "
  "The original model therefore flags ordinary links and passes phishing addresses that are dressed in the dataset's legitimate format.")
FIG("short", "fig11_shortcut.png", "Feature-set ablation (a) and the effect of cosmetic changes on the original and host-name models (b), web-address data.", width=6.6)
LEGIT_CHANGES = ("remove the www prefix", "use http instead of https", "add a trailing slash", "add a path")
REWRITE = "rewrite as https://www.<host> (legitimate template)"
base_fl = ppt["legitimate"]["as released"]["flagged_share"]
orig_checks = [ppt["legitimate"][k]["flagged_share"] - base_fl <= 0.05 for k in LEGIT_CHANGES] + [ppt["phishing"][REWRITE]["flagged_share"] >= 0.8 * ppt["phishing"]["as released"]["flagged_share"]]
orig_pass = sum(orig_checks)
hm_rows = [["Original logistic regression (31 features)", f"{f(PLR['test']['pr_auc'])} {band_br(bp, 'logistic_regression', 'pr_auc')}", f(PLR["test"]["precision"]), f(PLR["test"]["recall"]), pc_(PLR["test"]["false_positive_rate"], 2),
            f"no ({orig_pass} of {len(orig_checks)} checks)"]]
for fam, m, name in (("logistic_regression", HMLR, "logistic regression"), ("hist_gradient_boosting", HM, "gradient boosting")):
    passed = sum(1 for c in m["invariance_checks"] if c["passed"])
    hm_rows.append([f"Host-name {name} (10 features)", f"{f(m['test']['pr_auc'])} {band_br(phm['bootstrap'], fam, 'pr_auc')}", f(m["test"]["precision"]), f(m["test"]["recall"]),
                    pc_(m["test"]["false_positive_rate"], 2), f"yes ({passed} of {len(m['invariance_checks'])} checks)"])
TAB("hostmodel", "Original and host-name address models on the same held-out addresses.", ["Model", "PR-AUC [95% CI]", "Precision", "Recall", "False-alarm rate", "Passes robustness gate"], hm_rows, [3.0, 1.9, 0.9, 0.8, 1.1, 1.5],
    note="Note. The host-name models use a threshold that allows at most 1% false alarms on out-of-fold training predictions; the original models use the F2 threshold.")
sp_ = {r["url"]: r for r in psp["rows"]}
min_rise = min(ppt["legitimate"][k]["flagged_share"] - base_fl for k in LEGIT_CHANGES)
assert all(c["passed"] for c in HM["invariance_checks"]) and len(HM["invariance_checks"]) == 5, "the text says that the host-name model passes all five checks"
host_flag_ordinary = sum(r["host_flagged"] for r in sp_ordinary)
host_flag_phish = sum(r["host_flagged"] for r in sp_phish)
small_biz = sp_by["https://my-small-grocery-lusaka-fresh-produce.com"]
P(f"The host-name model that replaced it ignores those cues, and the robustness gate confirms it: all five checks pass, whereas the original model's flagged share of legitimate addresses rises by "
  f"at least {100 * min_rise:.1f} percentage points under each change. The price is accuracy. The gradient-boosting host-name model reaches a PR-AUC of {f(HM['test']['pr_auc'])} "
  f"(95% interval {band(phm['bootstrap'], 'hist_gradient_boosting', 'pr_auc')}), with precision {f(HM['test']['precision'])}, recall {f(HM['test']['recall'])} and a false-alarm rate of {pc_(HM['test']['false_positive_rate'], 2)}. "
  f"On the spot-check list it flagged {host_flag_ordinary} of the {len(sp_ordinary)} ordinary addresses and {host_flag_phish} of the {len(sp_phish)} phishing addresses from the data; sparkasse-auth.com scored {f(sp_by['https://sparkasse-auth.com/']['host_probability'], 2)}, "
  f"below the threshold of {f(psp['host_model_threshold'], 2)}. The legitimate addresses in the benchmark are popular sites with short names, so a small business with a long hyphenated name can be flagged. An invented address of that kind "
  f"(my-small-grocery-lusaka-fresh-produce.com) scored {f(small_biz['host_probability'], 2)}. We therefore keep the model experimental, and the ScamWatch checker does not use it.")
P(T("{T:comp} places the original result beside published results on the same dataset and the same task. The comparison is indicative only: our split keeps domains apart and our features come from "
    "address text alone, whereas the preprint does not state its split in the abstract [[Emmanuel2026]]. Given the findings above, scores near 99% on this dataset say more about how the legitimate addresses were written than about "
    "detecting phishing, and we do not claim that either result transfers to real links."))
pt_ = PLR["test"]
TAB("comp", "Web-address detection: this study and published studies.", ["Study", "Data and features", "Accuracy", "Precision", "Recall", "F1", "ROC-AUC"], [
    ["This study, original logistic regression", "PhiUSIIL; 31 address-text features; domain-grouped split", pc_(pt_["accuracy"], 2), pc_(pt_["precision"], 2), pc_(pt_["recall"], 2), pc_(pt_["f1"], 2), pc_(pt_["roc_auc"], 2)],
    ["This study, host-name gradient boosting", "PhiUSIIL; 10 host-name features; domain-grouped split; 1% false-alarm threshold", pc_(HM["test"]["accuracy"], 2), pc_(HM["test"]["precision"], 2), pc_(HM["test"]["recall"], 2), pc_(HM["test"]["f1"], 2), pc_(HM["test"]["roc_auc"], 2)],
    ["[[n:Emmanuel2026]]", "PhiUSIIL; 16 structure features; split not stated in the abstract", "99.24%", "98.74%", "99.95%", "99.34%", "99.65%"],
    ["[[n:Sahingoz2019]]", "Authors' own URL data; language-based features", "97.98%", "not quoted", "not quoted", "not quoted", "not quoted"],
], [2.4, 3.4, 0.9, 0.9, 0.9, 0.8, 0.9], leftAll=False, note="Note. Published figures are copied from the cited abstracts.")
H2("4.10 System verification and performance")
facts = sf
lat_c, lat_e = sl["checkout_post_orders"], sl["rule_engine_compute_only"]
ci_run = facts.get("ci_latest", {})
TAB("sys", "Verification and performance of the implementation.", ["Item", "Result"], [
    ["Backend automated tests (pytest)", f"{tr_['backend_passed']} passed on Windows with Python {cb['environment']['python']}; the suite also passes on Linux with Python 3.12 in continuous integration"],
    ["Frontend unit tests (vitest) and browser tests (Playwright)", f"{tr_['vitest_passed']} and {tr_['playwright_passed']}, all passing"],
    ["Continuous integration", ", ".join(f"{k}: {v}" for k, v in ci_run.get("jobs", {}).items()) + f" (run {ci_run.get('run_number')}, commit {ci_run.get('commit')})"],
    ["Route security test", f"Every API operation refuses anonymous callers unless it is on a reviewed list of {len(PUBLIC)} public operations; every staff operation refuses a customer token"],
    ["API operations; database tables", f"{facts['api_operations']}; {facts['database_tables']}"],
    ["Checkout request (POST /orders), in-process, SQLite", f"median {lat_c['p50_ms']:.0f} ms, 95th percentile {lat_c['p95_ms']:.0f} ms ({sl['n_orders']} orders)"],
    ["Rule engine computation alone", f"median {lat_e['p50_ms']:.1f} ms, 95th percentile {lat_e['p95_ms']:.1f} ms"],
    ["Card model scoring (one transaction)", f"median {clat['models']['creditcard_pca']['p50_ms']:.1f} ms, 95th percentile {clat['models']['creditcard_pca']['p95_ms']:.1f} ms"],
    ["Address model scoring (one address)", f"median {clat['models']['url_phishing']['p50_ms']:.1f} ms, 95th percentile {clat['models']['url_phishing']['p95_ms']:.1f} ms"],
    ["Training time, card data (one run each)", f"logistic regression {LR['seconds']:.0f} s, gradient boosting {HG['seconds']:.0f} s, random forest {RF['seconds']:.0f} s, including cross-validation, on {env['cpu_count']} logical processors"],
], [3.2, 5.8], leftAll=True, note="Note. Latencies are indicative: single thread, no network, local database.")
P("The tests cover the behaviours this paper depends on: idempotent checkout, unsupported and invalid model input, the alert policy for experimental and validated models, append-only outcomes, label export that ignores "
  "unverified outcomes, refusal to train without enough labels, the address-model robustness gate, and access separation between customers and staff. The route-security test addresses broken function-level "
  "authorisation, one of the risks in the OWASP API Security Top 10 [[OWASP2023]]; it is not a penetration test. Running continuous integration on a newer FastAPI release also exposed a flaw in that test: it listed routes "
  "through an internal structure that the release had changed, and found none. The test now reads the routes from the OpenAPI schema and asserts a minimum route count.")

# ============================================================================================================ 5 Discussion
H1("5. Discussion")
BUL([
    "*RQ1.* A store can assess orders with twelve fields it already records, and the rule engine can explain every score in words.",
    f"*RQ2.* A random forest is the best of three standard classifiers on the card data (PR-AUC {f(RF['test']['pr_auc'])}), but the estimate is uncertain: the interval runs from {band(bc, 'random_forest', 'pr_auc')}, and "
    f"five random splits span {f(sr['pr_auc']['min'])} to {f(sr['pr_auc']['max'])}.",
    "*RQ3.* Careless evaluation can turn the same model into a near-perfect one, and the web-address data reward formatting cues that real links will not share.",
    "*RQ4.* The public datasets cannot support a grocery model because they lack the store's fields, so the store records an explicit refusal and collects verified outcomes instead.",
    "*RQ5.* Class-weighted models need calibration before their scores can be read as probabilities, and the card model relies on a handful of anonymised components.",
])
P(f"We trained a web-address model, validated it on held-out domains and obtained a PR-AUC of {f(PLR['test']['pr_auc'])}. Only a perturbation test, which no standard metric requires, showed that it "
  "had learned how the legitimate list was written. A held-out score cannot reveal a flaw that the training and test partitions share. The remedy we adopted is a test that edits one cue at a time, applied "
  "as a gate before promotion, together with the rule that no address-model verdict reaches a user while it is experimental.")
P("The framework avoids claims the data cannot support. A model that has not seen a field is not asked about it, an order that no one has reviewed is not labelled legitimate, and a model with too little "
  "evidence is kept out of the alert path. The price is some convenience, because the store starts with rules and not with a learned model.")
P("The results agree with the cautions in the literature. The inflation from oversampling before the split matches the warning that leakage can produce near-perfect recall [[Hayat2025]], and the web-address data "
  "show the kind of cue that shortcut learning predicts [[Geirhos2020]]. Our random forest beat logistic regression and gradient boosting, in line with the strength of tree ensembles on tabular data [[Grinsztajn2022]], "
  "but the same ordering is not guaranteed on another dataset, and the PR-AUC and ROC-AUC rankings disagree here. The practical implication for a retailer is to report precision-recall results with intervals and "
  "to ask any vendor which protocol produced a quoted score.")
P(f"The experiments have limits of their own. The card data are from 2013 and hold {RF['split']['test_class_counts']['fraud']} fraud rows in the test partition, so precision and recall are imprecise. The five repeated splits reuse the same data and "
  "are not independent. The host-name model ranks address texts and says little about a link to a compromised legitimate site. The rule engine's points were set by judgement, not fitted, and "
  "its performance on real fraud is unknown. Section 7 discusses the remaining limits.")

# ============================================================================================================ 6 Applications
H1("6. Real-world applications")
P("The framework suits any merchant that accepts mobile money or card online and has no fraud history to learn from. The rule engine gives a new store a documented, adjustable policy from its first order. "
  "The schema guard and the verified-outcome log let it collect labels at the same time, and the promotion gate says when a trained model has earned a place in the alert path.")
P("Payment aggregators and mobile money providers could use the same pattern for merchants that are too small to receive a bespoke model: a rule baseline, an explicit unsupported status, and a shadow-mode "
  "comparison. ScamWatch, the address checker in the application, is a consumer-facing use. It combines offline address heuristics with a Safe Browsing lookup when a key is configured; we have not tested that lookup live. "
  "It only ever raises suspicion, and it tells the user that a result of no known threat does not mean a website is safe. The trained address model is not part of its verdicts. "
  "The audit trail of assessments and outcomes also gives a regulator or auditor something concrete to inspect.")
P("The evaluation protocol in Section 3 does not depend on the store's fields, so other teams can apply it to their own fraud or phishing data, in banking, cybersecurity or public-sector payment services.")

# ============================================================================================================ 7 Challenges
H1("7. Challenges and limitations")
BUL([
    "*Dataset limitations.* The card data are anonymised, two days long and from 2013. PaySim and MoMTSim are simulations. In the phishing dataset every legitimate address is a bare, secure, www-prefixed site root, "
    "so it cannot support a deployable address model; that needs legitimate addresses sampled like real traffic, with paths, plain http and small sites. No public dataset carries a grocery order's fields, "
    "and the store has no verified fraud labels yet, so no claim is made about fraud detection on store orders.",
    f"*Computational complexity.* All models trained in minutes on one ordinary computer (random forest {RF['seconds'] / 60:.0f} minutes including cross-validation), and scoring takes milliseconds, so complexity is not a barrier for a small store.",
    "*Privacy and security.* The schema holds no names, contact details, address text or card data; the application does not store card numbers, which stay with the payment provider. Zambia's Data Protection Act "
    "regulates the collection, use, storage and transfer of personal data [[Zambia2021]], and a deployment would have to meet its duties as a data controller. We did not assess compliance in this study.",
    "*Ethical concerns.* A false alarm costs a customer time or a cancelled order. The system therefore never blocks an order or a payment; it asks a person to look. We did not test whether flag rates differ between groups "
    "of customers, and behavioural fields such as order timing and address reuse could correlate with such groups.",
    "*Scalability.* The service runs as one process with an in-memory rate limiter and background jobs inside the process. This suits a small store; a larger one would need shared rate limiting and a job queue.",
    "*Label quality.* Reviewers can verify only what evidence allows, so some fraud will be labelled legitimate or undetermined, and some verified labels will come from the orders the rules flagged. The audit sample limits "
    "but does not remove this selection effect [[Lakkaraju2017]].",
])

# ============================================================================================================ 8 Future work
H1("8. Future work")
BUL([
    "Collect verified outcomes for several months, including the weekly audit sample, and train the first store model in shadow mode.",
    "Compare that model with the rule engine on the same held-out customers, as the promotion gate requires, and publish the comparison with intervals.",
    "Build an address benchmark whose legitimate half is sampled like real traffic, retrain under the robustness gate, and test on links reported by users.",
    "Monitor drift in order fields and in model scores, and retrain on a schedule with the same gate.",
    "Add mobile-money-specific rules and test them on simulated data from PaySim and MoMTSim, clearly labelled as simulation.",
    "Study whether merchants could pool signals without sharing orders, for example through federated learning, and measure analyst workload with the alert policy.",
])

# ============================================================================================================ 9 Conclusion
H1("9. Conclusion")
P(f"This study set out to build and evaluate an auditable risk-assessment framework for a small online grocery store. The framework scores orders with a documented rule engine, refuses to score inputs a model never saw, "
  f"and records verified outcomes for later training. Under a leakage-controlled protocol, a random forest detected card fraud with a PR-AUC of {f(RF['test']['pr_auc'])} (95% interval {band(bc, 'random_forest', 'pr_auc')}), "
  f"and evaluation shortcuts moved the same model's score between {f(protoA['pr_auc'], 2)} and {f(protoB['pr_auc'], 2)}. A web-address model that scored {f(PLR['test']['pr_auc'])} had learned the formatting of the "
  f"legitimate list, which a perturbation test exposed; a robustness gate now blocks such models, and the host-name model that replaced it reaches a PR-AUC of {f(HM['test']['pr_auc'])} and is kept experimental. "
  f"{NUM_WORD.get(N_SCEN, str(N_SCEN)).capitalize()} scripted checkouts showed the rule engine behaving as specified, and automated tests and continuous integration support the implementation.")
P("The next step is empirical: collect verified grocery outcomes and test whether a model can beat the rules on held-out customers. Until then, the store's answer to the question \"is this order fraud?\" is a score "
  "with reasons for a person to review, and an explicit statement when no model can say more.")

# ============================================================================================================ back matter
H1("Acknowledgement")
P("The ULB Machine Learning Group and Worldline collected and released the card data, which we obtained through OpenML. Prasad and Chandra released the phishing data under a CC BY 4.0 licence, which we obtained from the UCI repository. "
  "The study used open-source software, including scikit-learn, FastAPI, React and PostgreSQL. " + AUTHOR["ai_statement"])
H1("Declarations")
P(AUTHOR["declarations"])
H1("References")
add("refs", items=[f"[{i}] {REFS[k][2]}" for i, k in enumerate(CITE_ORDER, start=1)])

# ------------------------------------------------------------------------------------------------------------ writing lint
# Patterns from the humanizer and clear-writing rules: no dashes used as connectors, no stock "AI" vocabulary, no staged contrasts.
EM, EN = chr(0x2014), chr(0x2013)
WB = chr(92) + "b"                                    # a regular-expression word boundary
BANNED_WORDS = ["additionally", "moreover", "furthermore", "crucial", "pivotal", "robust", "landscape", "highlight", "underscore", "showcase", "valuable", "testament",
                "intricate", "delve", "tapestry", "meticulous", "seamless", "holistic", "leverage", "comprehensive", "cutting-edge", "game-changing", "paramount",
                "it is worth noting", "it's worth noting", "in conclusion", "notably", "importantly", "vital", "key role", "plays a", "in today's", "rapidly evolving"]
STAGED = ["not (just|only|merely)", "it'?s not", "isn'?t (just|about)", "rather than", "this (does not|doesn't) mean", "the real (question|issue|problem)", "let'?s", "here'?s", "that'?s the"]
lint_hits = []


def lint(t):
    if EM in t or EN in t:
        lint_hits.append(("dash", t[:80]))
    low = t.lower()
    for w in BANNED_WORDS:
        if re.search(WB + re.escape(w) + WB, low):
            lint_hits.append((w, t[:80]))
    for pat in STAGED:
        if re.search(WB + pat + WB, low):
            lint_hits.append((pat, t[:80]))


for b in blocks:
    if isinstance(b.get("text"), str):
        lint(b["text"])
    for it in b.get("items", []) if isinstance(b.get("items"), list) else []:
        if isinstance(it, str):
            lint(it)
for kind, snippet in lint_hits:
    print(f"LINT [{kind}] {snippet}")
print(f"lint: {len(lint_hits)} hit(s)")

# ------------------------------------------------------------------------------------------------------------ checks
unused = set(REFS) - set(CITE_ORDER)
if unused:
    raise SystemExit(f"references never cited: {sorted(unused)}")
wc_abs = len(ABSTRACT.split())
print(f"abstract words: {wc_abs}")
assert 200 <= wc_abs <= 250, f"abstract must be 200-250 words (is {wc_abs})"
assert 5 <= len([k for k in KEYWORDS.split(';')]) <= 6

content = {"meta": {"creator": AUTHOR["creator"], "docTitle": TITLE, "description": "Journal manuscript", "corresponding": AUTHOR["corresponding_lines"]}, "blocks": blocks}
out_json = HERE / "content.json"
out_json.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf8")
print(f"wrote {out_json.name}: {len(blocks)} blocks, {len(CITE_ORDER)} references cited")

if "--no-render" not in sys.argv:
    docx_out = HERE / "manuscript.docx"
    env = dict(os.environ)
    nm = os.environ.get("PAPER_NODE_MODULES")
    if nm:
        env["NODE_PATH"] = nm
    r = subprocess.run(["node", str(HERE / "render_docx.js"), str(out_json), str(docx_out)], capture_output=True, text=True, env=env)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode:
        sys.exit(r.returncode)
