"""Reference list for the manuscript, written in the format that the journal asks for on https://www.multiresearchjournal.com/instructions
(read on 2026-10-23):

    Journal article:  Author(s) name. Title of article. Title of journal. Year; Volume(Issue): Page No.
    Book or chapter:  Author(s) name. Title. Place, Publisher, Year, Page No.
    Report or web:    Author. Title. Publisher, Year. Retrieved from: web address.

In the text, citations are numbered in order of first appearance, as [1], [2, 5] or [3-6]. Every entry was checked against Crossref (journal
articles and proceedings, by DOI), the publisher or arXiv page, or the document itself (GSMA report, Zambian Act, OWASP page).
Vancouver-style author names (surname, initials without full stops); more than six authors are cut to six followed by "et al.".
Each REFS value is (name used in running text, year, formatted entry)."""

MAX_AUTHORS = 6


def _authors(people):
    names = [f"{s} {i}" for s, i in people]
    return ", ".join(names[:MAX_AUTHORS]) + (", et al." if len(names) > MAX_AUTHORS else ".")


def _short(people):
    """How the authors are named in a sentence: Breiman, Hayat and Magnier, Dal Pozzolo et al."""
    s = [p[0] for p in people]
    return s[0] if len(s) == 1 else f"{s[0]} and {s[1]}" if len(s) == 2 else f"{s[0]} et al."


def _doi(doi):
    return f" https://doi.org/{doi}" if doi else ""


def _title(title):
    """A title ends with one full stop, not two (titles that end in a question mark keep it)."""
    return title if title[-1] in ".?!" else title + "."


def article(people, year, title, journal, volume, issue=None, pages=None, doi=None):
    loc = f"{volume}" + (f"({issue})" if issue else "") + (f":{pages}" if pages else "")
    return (_short(people), year, f"{_authors(people)} {_title(title)} {journal}. {year}; {loc}.{_doi(doi)}")


def chapter(people, year, title, book, publisher, pages=None, doi=None, url=None):
    tail = f" Retrieved from: {url}" if url and not doi else _doi(doi)
    return (_short(people), year, f"{_authors(people)} {_title(title)} In: {book}. " + (f"{publisher}, " if publisher else "") + f"{year}" + (f", {pages}" if pages else "") + f".{tail}")


def preprint(people, year, title, ident):
    return (_short(people), year, f"{_authors(people)} {_title(title)} arXiv preprint. {year}; arXiv:{ident}. Retrieved from: https://arxiv.org/abs/{ident}")


def document(organisation, year, title, publisher, url):
    return (organisation, year, f"{organisation}. {_title(title)} " + (f"{publisher}, " if publisher else "") + f"{year}. Retrieved from: {url}")


REFS = {
    "Azamuke2024": article([("Azamuke", "D"), ("Katarahweire", "M"), ("Bainomugisha", "E")], 2024,
                           "MoMTSim: A multi-agent-based simulation platform calibrated for mobile money transactions", "IEEE Access", 12, pages="120226-120238",
                           doi="10.1109/ACCESS.2024.3439012"),
    "Boyd2013": chapter([("Boyd", "K"), ("Eng", "KH"), ("Page", "CD")], 2013, "Area under the precision-recall curve: Point estimates and confidence intervals",
                        "Machine Learning and Knowledge Discovery in Databases (ECML PKDD 2013)", "Springer", "451-466", doi="10.1007/978-3-642-40994-3_29"),
    "Breiman2001": article([("Breiman", "L")], 2001, "Random forests", "Machine Learning", 45, 1, "5-32", "10.1023/A:1010933404324"),
    "Carcillo2021": article([("Carcillo", "F"), ("Le Borgne", "YA"), ("Caelen", "O"), ("Kessaci", "Y"), ("Oblé", "F"), ("Bontempi", "G")], 2021,
                            "Combining unsupervised and supervised learning in credit card fraud detection", "Information Sciences", 557, pages="317-331",
                            doi="10.1016/j.ins.2019.05.042"),
    "Chicco2020": article([("Chicco", "D"), ("Jurman", "G")], 2020, "The advantages of the Matthews correlation coefficient (MCC) over F1 score and accuracy in binary classification evaluation",
                          "BMC Genomics", 21, pages="6", doi="10.1186/s12864-019-6413-7"),
    "DP2018": article([("Dal Pozzolo", "A"), ("Boracchi", "G"), ("Caelen", "O"), ("Alippi", "C"), ("Bontempi", "G")], 2018,
                      "Credit card fraud detection: A realistic modeling and a novel learning strategy", "IEEE Transactions on Neural Networks and Learning Systems", 29, 8,
                      "3784-3797", "10.1109/TNNLS.2017.2736643"),
    "DP2015": chapter([("Dal Pozzolo", "A"), ("Caelen", "O"), ("Johnson", "RA"), ("Bontempi", "G")], 2015, "Calibrating probability with undersampling for unbalanced classification",
                      "2015 IEEE Symposium Series on Computational Intelligence", "IEEE", "159-166", doi="10.1109/SSCI.2015.33"),
    "Dietterich1998": article([("Dietterich", "TG")], 1998, "Approximate statistical tests for comparing supervised classification learning algorithms", "Neural Computation", 10, 7,
                              "1895-1923", "10.1162/089976698300017197"),
    "Efron1979": article([("Efron", "B")], 1979, "Bootstrap methods: Another look at the jackknife", "The Annals of Statistics", 7, 1, "1-26", "10.1214/aos/1176344552"),
    "Elor2022": preprint([("Elor", "Y"), ("Averbuch-Elor", "H")], 2022, "To SMOTE, or not to SMOTE?", "2201.08528"),
    "Emmanuel2026": preprint([("Emmanuel", "UU"), ("Oghie", "GF")], 2026,
                             "A lightweight hybrid MLP-based framework for real-time phishing URL detection using structural URL features", "2606.00889"),
    "Geirhos2020": article([("Geirhos", "R"), ("Jacobsen", "JH"), ("Michaelis", "C"), ("Zemel", "R"), ("Brendel", "W"), ("Bethge", "M"), ("Wichmann", "FA")], 2020,
                           "Shortcut learning in deep neural networks", "Nature Machine Intelligence", 2, 11, "665-673", "10.1038/s42256-020-00257-z"),
    "Grinsztajn2022": article([("Grinsztajn", "L"), ("Oyallon", "E"), ("Varoquaux", "G")], 2022, "Why do tree-based models still outperform deep learning on typical tabular data?",
                              "Advances in Neural Information Processing Systems", "35 (Datasets and Benchmarks Track)"),
    "GSMA2025": document("GSMA", 2025, "The state of the industry report on mobile money 2025", "GSM Association",
                         "https://www.gsma.com/sotir/wp-content/uploads/2025/04/The-State-of-the-Industry-Report-2025_English.pdf"),
    "Hayat2025": article([("Hayat", "K"), ("Magnier", "B")], 2025, "Data leakage and deceptive performance: A critical examination of credit card fraud detection methodologies",
                         "Mathematics", 13, 16, "2563", "10.3390/math13162563"),
    "Hilal2022": article([("Hilal", "W"), ("Gadsden", "SA"), ("Yawney", "J")], 2022, "Financial fraud: A review of anomaly detection techniques and recent advances",
                         "Expert Systems with Applications", 193, pages="116429", doi="10.1016/j.eswa.2021.116429"),
    "Kapoor2023": article([("Kapoor", "S"), ("Narayanan", "A")], 2023, "Leakage and the reproducibility crisis in machine-learning-based science", "Patterns", 4, 9, "100804",
                          "10.1016/j.patter.2023.100804"),
    "Kaufman2012": article([("Kaufman", "S"), ("Rosset", "S"), ("Perlich", "C"), ("Stitelman", "O")], 2012, "Leakage in data mining: Formulation, detection, and avoidance",
                           "ACM Transactions on Knowledge Discovery from Data", 6, 4, "15", "10.1145/2382577.2382579"),
    "Lakkaraju2017": chapter([("Lakkaraju", "H"), ("Kleinberg", "J"), ("Leskovec", "J"), ("Ludwig", "J"), ("Mullainathan", "S")], 2017,
                             "The selective labels problem: Evaluating algorithmic predictions in the presence of unobservables",
                             "Proceedings of the 23rd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining", "ACM", "275-284", doi="10.1145/3097983.3098066"),
    "LopezRojas2016": chapter([("Lopez-Rojas", "EA"), ("Elmir", "A"), ("Axelsson", "S")], 2016, "PaySim: A financial mobile money simulator for fraud detection",
                              "Proceedings of the 28th European Modeling and Simulation Symposium (EMSS 2016)", None, url="https://msc-les.org/proceedings/emss/emss2016/emss2016_249.html"),
    "Mutemi2023": article([("Mutemi", "A"), ("Bacao", "F")], 2023, "A numeric-based machine learning design for detecting organized retail fraud in digital marketplaces", "Scientific Reports", 13, 1,
                          "12499", "10.1038/s41598-023-38304-5"),
    "Mutemi2024": article([("Mutemi", "A"), ("Bacao", "F")], 2024, "E-commerce fraud detection based on machine learning techniques: Systematic literature review",
                          "Big Data Mining and Analytics", 7, 2, "419-444", "10.26599/BDMA.2023.9020023"),
    "Niculescu2005": chapter([("Niculescu-Mizil", "A"), ("Caruana", "R")], 2005, "Predicting good probabilities with supervised learning",
                             "Proceedings of the 22nd International Conference on Machine Learning", "ACM", "625-632", doi="10.1145/1102351.1102430"),
    "OWASP2023": document("OWASP Foundation", 2023, "OWASP API security top 10: 2023", None, "https://owasp.org/API-Security/editions/2023/en/0x00-header/"),
    "Pedregosa2011": article([("Pedregosa", "F"), ("Varoquaux", "G"), ("Gramfort", "A"), ("Michel", "V"), ("Thirion", "B"), ("Grisel", "O"), ("Blondel", "M"), ("Prettenhofer", "P"),
                              ("Weiss", "R"), ("Dubourg", "V"), ("Vanderplas", "J"), ("Passos", "A"), ("Cournapeau", "D"), ("Brucher", "M"), ("Perrot", "M"), ("Duchesnay", "E")], 2011,
                             "Scikit-learn: Machine learning in Python", "Journal of Machine Learning Research", 12, pages="2825-2830"),
    "Prasad2024": article([("Prasad", "A"), ("Chandra", "S")], 2024, "PhiUSIIL: A diverse security profile empowered phishing URL detection framework based on similarity index and incremental learning",
                          "Computers & Security", 136, pages="103545", doi="10.1016/j.cose.2023.103545"),
    "Safi2023": article([("Safi", "A"), ("Singh", "S")], 2023, "A systematic literature review on phishing website detection techniques", "Journal of King Saud University - Computer and Information Sciences",
                        35, 2, "590-611", "10.1016/j.jksuci.2023.01.004"),
    "Sahingoz2019": article([("Sahingoz", "OK"), ("Buber", "E"), ("Demir", "O"), ("Diri", "B")], 2019, "Machine learning based phishing detection from URLs", "Expert Systems with Applications", 117,
                            pages="345-357", doi="10.1016/j.eswa.2018.09.029"),
    "Saito2015": article([("Saito", "T"), ("Rehmsmeier", "M")], 2015, "The precision-recall plot is more informative than the ROC plot when evaluating binary classifiers on imbalanced datasets",
                         "PLOS ONE", 10, 3, "e0118432", "10.1371/journal.pone.0118432"),
    "Zambia2021": document("Republic of Zambia", 2021, "The Data Protection Act, 2021 (Act No. 3 of 2021)", None, "https://zambialii.org/akn/zm/act/2021/3/eng@2021-03-24"),
}

assert len(REFS) == 30, len(REFS)
