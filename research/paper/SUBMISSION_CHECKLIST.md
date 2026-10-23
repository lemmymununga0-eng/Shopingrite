# Submission checklist

Prepared 23 October 2026 for *International Journal of Advanced Multidisciplinary Research and Studies* (multiresearchjournal.com).
Everything about the journal below was read from its own pages on that date.

## 1. Files

| File | Purpose |
|---|---|
| `manuscript.docx` | The paper, in the journal's format. Upload this. |
| `manuscript.pdf` | The same paper as exported by Word, for checking the layout. |
| `cover_letter.docx` | Draft letter to the editor. |
| `../figures/*.png` | The 13 figures (already embedded in the manuscript). |
| `../results/*.json` | The saved results that every number in the paper is generated from. |

Rebuild after any change: `cd research/paper && python build.py && python build_cover.py` (see `../README.md`).

## 2. Fill in before you send

The manuscript and letter contain these placeholders. Search for `[`:

- Author name, **surname first**, with an asterisk for the corresponding author (the journal asks for this).
- Department, university or organisation, city, country.
- Postal address and phone number for the corresponding-author block at the lower left of page 1.
- E-mail. I used `lemmymununga0@gmail.com`, the address on your account. Replace it with an institutional address if you have one.
- Date in the cover letter.

## 3. Confirm that each statement is true

The paper and letter say these things on your behalf. Change them if any is wrong.

- The work is original, unpublished and not under review elsewhere.
- No conflict of interest and no external funding (Declarations).
- No human participants or personal data were involved; the checkout customers are synthetic.
- You have read the whole paper, checked it against the code and results, and are responsible for it.
- An AI assistant helped to write the software, scripts and text (Acknowledgement). I kept this statement. The journal pages I read contain no AI policy, so ask them if you are unsure. I edited the text for plain, specific prose; I did not try to hide how it was written, and I recommend you do not either.
- The GitHub repository is public (checked on 23 October 2026) and will carry the release tag `paper-v1`. Consider adding a licence file so that reuse terms are clear.

## 4. What the journal asks for

From the Instruction, Editorial policies, Peer review, Plagiarism and Terms pages:

- **Online form** at `/submission`: name, e-mail, phone, institute address, manuscript title, and one file.
- **Fee**: 30 USD for international authors (1444 INR in India), "with DOI". The refund page says 25% plus transaction charges is kept if you cancel after paying but before final submission, and nothing is refunded after payment and final submission. Read it before you pay.
- **Author Responsibility Form**: a Word file linked at the bottom of the Instruction page. Download it, complete it and attach it. I did not download or read it.
- **Consent**: the Terms say you have the consent of your institution, supervisor and co-authors.
- **Similarity**: they check after submission and reject above 35%. Run your own check first; the paper is original, but code identifiers and standard method phrases will count.
- **Review**: double blind, at least two experts, editor's decision final, no time promised. The Declarations name the GitHub account, which identifies you. Remove or anonymise that URL if the editor asks for a blinded file.
- **Copyright**: after acceptance you sign a copyright agreement. The Editorial policies page says you keep copyright; the Terms page says the journal keeps it. Ask which applies before you pay.

## 5. Format compliance

| Requirement | Status |
|---|---|
| A4, 1 inch margins, Times New Roman, single spacing, numbered pages | Done |
| Title 14 pt bold sentence case; headings 10 pt bold | Done |
| Abstract 100 to 250 words (template: 200 to 250) | 236 words |
| 4 to 6 keywords (template: 5 to 7) | 6 |
| Corresponding author marked `*`, address at the lower left of page 1 | Done |
| References numbered in the journal's author-initials style, 20 to 30 of them | 30, numbered in order of citation |
| Your template's sections 1 to 9, tables and figures | Done; a feature-importance figure replaces SHAP and LIME, which do not apply |

Two judgement calls:

- **References.** Your template says "follow the journal's required citation style (APA)". The journal's own Instruction page shows a different style (author initials, no brackets round the year, for example `Skrzypacz J, Bieganowski M. Title. Journal. 2018; 144:827-835.`), so I followed the journal.
- **Sections.** The journal lists Introduction, Materials and Methods, Results and Discussion, Conclusion. I kept your template's longer structure. If the editor insists, merge sections 4 and 5.

## 6. An honest view of this journal

I cannot guarantee that any paper is accepted, and I cannot promise that this venue carries weight. What I could verify:

- **Scope is everything.** The Aims page lists "basic and applied science, technology, engineering, medicine, management, politics, law, arts and humanities". The current issue mixes biochemistry, education, agriculture, law, physics and computer science.
- **It charges a fee** and states no time to decision. Acceptance after a light review is likely; that is not the same as a strong peer review.
- **Indexing is unclear.** The ISSN portal record (2583-049X; OPRA Publications, India; started 2021; record created February 2022) lists three indexing sources: Crossref, OpenAlex and Title DOI. Those are DOI and open-catalogue services that include almost any article with a DOI; they are not selective journal indexes. I found no sign of Scopus, Web of Science or DOAJ. A third-party directory states that the journal is not in Scopus, Web of Science, DOAJ, PubMed or UGC CARE, and lists an impact factor of 3.978 attributed to Google Scholar, which does not assign impact factors. The journal's Indexing page shows five logos without names, and its Editorial policies page says that each year's articles "will then be submitted for indexing purposes".
- **Small signals.** The contact address is a Gmail account, the phone number shown differs from the number in its link, and the Terms contain clauses that bar authors from sharing the journal's e-mails publicly and from seeking any refund.

These are common marks of low-quality pay-to-publish journals. I have no evidence of fraud, but if the paper must count for a job, a degree or a promotion, ask your institution whether this journal is accepted, and check the Scopus source list, the Web of Science Master Journal List and DOAJ yourself.

The paper itself is stronger than this venue. If you have time, consider:

1. Posting a preprint with a free DOI (for example on Zenodo) so the work is citable at once.
2. Submitting to an indexed journal or workshop on fraud detection, applied machine learning or cybersecurity. Expect harder reviewers. They will ask for the points in section 7.

## 7. Weak points a reviewer will raise

The paper already states each of these. Expect questions anyway.

- No real grocery fraud labels exist, so the store's fraud detection is unproven. The paper offers a rule engine and a label-collection protocol, not a detection result.
- The card data are from 2013, with 95 fraud rows in the test partition, so precision and recall are imprecise.
- The web-address dataset has a collection artefact. The paper reports this as a negative result and replaces the model with a weak host-name model that stays experimental.
- The classifiers are standard. The contribution is the framework, the protocol and the measured effect of evaluation shortcuts.
- One author, and AI assistance in the writing and the code.

## 8. Before you press submit

1. Read the whole PDF once, including every table.
2. Check that `research/results/test_runs.json` and the CI run named in Table 17 still match the repository.
3. Confirm that the repository's `paper-v1` tag exists and that the README's research section opens.
4. Fill the placeholders, sign the Author Responsibility Form, and keep copies of everything you send and pay.
