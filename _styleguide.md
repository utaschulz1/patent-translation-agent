# Patent Translation Style Guide — EN → DE
**Client: Comunica DK / Welocalize**
**Sources:** Patent Style Guide v6 (February 2026, PDF) [priority] + EN-DE Notes on patent translations (June 2025, DOCX)

---

## 1. Accuracy & Faithfulness to Source

- **1 claim = 1 sentence.** Never split a claim into multiple sentences.
- **Omissions and additions** always alter the scope of the invention — avoid both.
- **Source errors:** Mirror errors in the translation; do not correct them. Only obvious typos with no impact on meaning (e.g., "hpme" → "home") or pure typography errors (repeated semicolon, missing comma) may be corrected. Report all other errors in a separate comment/errata document.
- **Reference numbers:** Reproduce exactly as in the source text. Never correct incorrect reference numbers — the error may be deliberate.
- **Ambiguity:** If the source text is deliberately or unavoidably ambiguous, reproduce the same level of ambiguity in the translation. Do not resolve ambiguity by choosing one interpretation.
- **Relative clauses:** Use the full patent description to determine what "each of which", "which" etc. refer to before committing to a German gender/article choice.
- **No annotations** (sic, footnotes, errata) inside the translation itself — provide them in a separate document.
- **No hyperlinks or browser-executable code** (e.g., URLs in `< >`) in the translation file — they constitute improper incorporation by reference.

---

## 2. Claims Structure (German-Specific Rules)

### 2.1 Preamble — no article
Claims preambles always start **without an article**, even for plural subjects:

| EN (wrong → right) | DE (wrong → right) |
|---|---|
| The compound or the pharmaceutically acceptable salt thereof | ~~Die Verbindung oder das pharmazeutisch annehmbare Salz~~ → **Verbindung oder pharmazeutisch annehmbares Salz** |

### 2.2 "comprising" → umfassend (preferred)
Translate the gerund **"comprising"** as **"umfassend"** (participial construction, no relative clause) rather than with a relative clause. The relative-clause approach requires correct gendered articles whose referent may be unclear, introducing error risk.

| EN | DE (avoid) | DE (preferred) |
|---|---|---|
| A blind spot warning system, comprising a controller comprising… | ~~das eine Steuervorrichtung umfasst, das/die … umfasst~~ | **umfassend eine Steuervorrichtung, umfassend…** |

- **"comprise"** (finite verb) → **"umfassen"** (relative clause with correct article is acceptable here).
- **"(further) comprising"** → **(ferner) umfassend** (preferred); "der/die/das … ferner umfasst" is acceptable as alternative if used consistently throughout the patent.

### 2.3 Method steps — verb-derived nouns (Nominalisierung)
In method claims, translate gerunds with **verb-derived nouns (Verbalsubstantiv)**, not result nouns:

| EN | Wrong | Correct |
|---|---|---|
| mixing two components | ~~Mischung von zwei Komponenten~~ | **Mischen von zwei Komponenten** |
| separating | ~~Trennung~~ | **Trennen / ein Trennen** |
| determining | ~~Bestimmung~~ | **Bestimmen** |

"Comprising the steps of [verb]-ing" → **"umfassend die Schritte eines [Nominalisierung]"** — do not add a colon, do not use infinitive form after colon.

Example:
- Wrong: `umfassend die Schritte: Bestimmen`
- Correct: `umfassend die Schritte eines Bestimmens`

### 2.4 Verb position in subordinate clauses (wobei)
In subordinate clauses (especially "wobei" clauses), the **verb belongs at the end**, after all elements it governs. Avoid placing the verb in the middle of the clause (colloquial style).

| | Example |
|---|---|
| Avoid | `wobei das System einen Speicher **umfasst**, der konfiguriert ist, … und eine Verarbeitungseinheit.` |
| Preferred | `wobei das System einen Speicher, der konfiguriert ist, …, und eine Verarbeitungseinheit **umfasst**.` |

Exception: if three or more verbs would end up consecutively, split the clause to preserve readability — place a verb before a nested subordinate clause.

### 2.5 Stative vs. eventive passive
**Stative passive** (describes a state): use **"ist … [Partizip II]"**
**Eventive passive** (describes an action): use **"wird … [Partizip II]"**

| Type | EN | DE |
|---|---|---|
| Stative | the corner portion is provided with a protrusion | der Eckabschnitt **ist** mit einem Vorsprung **bereitgestellt** |
| Eventive | when the second composition is mixed with said first composition | wenn die zweite Zusammensetzung … **gemischt wird** |

When in doubt, prefer stative passive.

---

## 3. Articles

1. **Mirror source articles as a general rule.**
   - EN "a user equipment" → DE "eine Benutzereinrichtung"
   - EN "the modification" → DE "das Modifizieren"

2. **If the source has no article:**
   - First mention → indefinite article in German.
   - All subsequent mentions → definite article.

3. **Verb-derived nouns (Nominalisierungen):**
   - First mention → indefinite article **or** no article (both acceptable).
     - "ein Trennen der Komponenten" OR "Trennen der Komponenten"
   - Subsequent mentions → definite article or no article (definite article improves readability).
   - **Never use a definite article on first mention**, even if this appears ungrammatical.

4. **Whichever article approach is chosen, apply it consistently throughout the patent.**

5. **"each of the first and second"** → **"jede/-r/-s des ersten und des zweiten"** (Example: "jede der ersten und der zweiten Vorrichtung").

---

## 4. Key Terminology

### 4.1 Mandatory translations (no alternatives)

| EN | DE | Notes |
|---|---|---|
| according to (in preamble) | **nach** | "nach Anspruch 1" — always "nach" in preambles (conventional patent phrasing) |
| according to (elsewhere) | nach / gemäß | both accepted |
| and/or | **und/oder** | NOT: "mindestens eines von" |
| at least | **mindestens** | NOT: "zumindest" |
| at the / in the / from the / to the | **bei dem / in dem / von dem / zu dem** | Avoid contracted forms: beim/im/vom/zum etc. — see §5.1 |
| based on | **basierend auf** | |
| be (is/are) expressing a value or state | **ist / sind** | NOT: "beträgt" — use "beträgt" only if it can be applied consistently throughout the entire patent (rarely possible) |
| characterized in that | **dadurch gekennzeichnet, dass** | |
| characterized by | **gekennzeichnet durch** | |
| comprising | **umfassend** | see §2.2 |
| comprise | **umfassen** | |
| configured to | **konfiguriert, um** | NOT: "so/dazu konfiguriert ist/sind, dass" |
| consist of | **bestehen aus** | NOT: "enthalten" |
| contain | **enthalten** | NOT: "bestehen aus" |
| device | **Vorrichtung** | |
| apparatus | **Einrichtung** | Alt: "Vorrichtung" only if "device" does not also appear in the patent |
| disclosure | **Offenbarung** | |
| dispose | **anordnen** | |
| essential | **wesentlich** | |
| fig. | **Fig.** | |
| figure | **Figur** | |
| for example | **zum Beispiel** | |
| form (verb) | **bilden** | NOT: "formen" or "verlaufen" |
| have | **aufweisen** | |
| having | **aufweisend** | |
| include | **aufweisen** or **beinhalten** | NOT: "umfassen" (reserved for "comprise") |
| in response to | **als Reaktion auf** | NOT: "in Reaktion auf" |
| less than | **weniger als** | Alt: "kleiner als" |
| method | **Verfahren** | |
| method of producing / method for producing | **Verfahren zum Herstellen** | NOT: "Verfahren zur Herstellung" or "Verfahren des Herstellens" |
| more than | **mehr als** | Alt: "größer als" |
| one or more of x and y | **eines oder mehrere von x und y** | |
| at least one of x, y and z | **mindestens eine/einer/eines von x, y und z** | NOT: "x, y und/oder z" |
| person skilled in the art | **Fachperson** | NOT: "Fachmann" (EPO now uses Fachperson) |
| preferably | **vorzugsweise** | |
| provide | **bereitstellen** | |
| respectively | **beziehungsweise** | NOT abbreviated as "bzw." |
| said | **der / die / das** (definite article) | NOT: "besagte/r/s", "dieser/genannter" |
| same (adjective, identical) | **gleiche/r/s** (check article) | NOT: "dieselbe/derselbe/dasselbe" — "dieselbe" implies identity of the exact same object, "gleiche" means of the same kind |
| so that | **sodass** | NOT: "derart dass" |
| state of the art | **Stand der Technik** | |
| subject (medical/chemical context) | **Subjekt** | NOT: "Patient" |
| such as | **wie** | |
| such that | **derart, dass** | NOT: "so dass" |
| summary of the invention | **Kurzdarstellung der Erfindung** | |
| using | **mithilfe** or **durch Verwenden** | NOT: "unter Verwendung" |
| vehicle | **Fahrzeug** | NOT: "Auto" (too colloquial) |
| claims 1–5 | **Ansprüche 1 bis 5** | |

### 4.2 "wherein X comprises:" (colon after umfasst)
When a finite "umfasst" is followed by a list, add **"Folgendes"**:
- Wrong: `wobei die Steuerschaltung (22) umfasst:`
- Correct: `wobei die Steuerschaltung (22) **Folgendes** umfasst:`

Same for "further comprises at least one of the following:":
- Correct: `mindestens eines der folgenden **Elemente** umfasst:`

---

## 5. Grammar & Syntax

### 5.1 Preposition contractions — avoid
Do **not** use contracted preposition+article forms in patent translations:

| Avoid | Use instead |
|---|---|
| im | in dem |
| vom | von dem |
| am | an dem |
| beim | bei dem |
| zum | zu dem |
| zur | zu der |

Exceptions: fixed expressions only where contraction is part of the standardized term — e.g., "im Wesentlichen", "zur Verwendung", "zum Beispiel".

### 5.2 Relative pronouns
Use **der/die/das** for relative clauses. **Avoid "welche/welcher/welches"** in patent text.

### 5.3 First and second elements — singular
"The first and second plates" (English uses plural loosely) → **"die erste und zweite Platte"** (German singular, when context shows one of each).
- Wrong: ~~die ersten und zweiten Platten~~
- Correct: **die erste und zweite Platte**

### 5.4 Bracket plurals
Reproduce bracket structures exactly as in the source. Only add "(s)"-style brackets if they appear in the source:
- EN "supporting surface(s)" → DE "Stützfläche(n)"
- EN "one or more supporting surfaces" → DE "eine oder mehrere Stützflächen" (no brackets)

### 5.5 "each of two" / "each of the first and second"
- "each of two" → **"jede/-r/-s von zwei"** (NOT: "jede/-r/-s der beiden")
- "each of the first and second [noun]" → **"jede/-r/-s des ersten und des zweiten [Noun]"**

---

## 6. Punctuation, Spacing & Formatting

### 6.1 Non-breaking spaces (NBSP)
Insert a **non-breaking space** (Ctrl+Shift+Space or Alt+0160) between number and unit:
- Correct: `10 km`, `10 mm`, `10 %`, `10 °C`, `10 U/min`
- **Exception:** No NBSP before the degree symbol alone: `10°` (no space), but `10 °C` (NBSP before °C).

### 6.2 Number ranges — en dash
Use an **en dash (–, Alt+0150)** for number ranges, not a hyphen:
- Correct: `FIG. 7–42`, `10–20 mm`
- Wrong: ~~FIG. 7-42~~

### 6.3 Punctuation mirroring
Mirror source punctuation in the translation. Exception: **commas** follow German grammar rules.

### 6.4 Units
- Units are **never converted** — translate literally as in the source.
- Use SI units per DPMA/EPO guidelines.

### 6.5 Formulas
- Translate terms within formulas.
- Mirror abbreviations with German abbreviations where a recognized one exists:
  - `d_safe` → `d_sicher`
  - `Tcal` → `TBer.`

---

## 7. Abbreviations & Acronyms

### 7.1 Standard abbreviation conversions

| EN | DE |
|---|---|
| i.e. | d. h. |
| e.g. | z. B. |
| vol. | Bd. |
| no. | Nr. (not for SEQ ID NO.) |
| U.S. patent | US-Patent |

### 7.2 Acronyms — mirror source approach
- **Source uses acronym only** → translation uses acronym only (e.g., "RF" → "HF").
- **Source uses written-out form + acronym** → translation uses both (e.g., "printed circuit board, PCB" → "Leiterplatte, PCB").
- Do **not** write out the acronym in the translation — risk of error.
- If no recognized German acronym exists, keep the English acronym.

### 7.3 Acronyms in compound nouns
Place the acronym so the compound makes sense without it, using hyphens:
- Correct: `Feldflussfraktionierungs(FFF)-Separator`
- Correct: `Uplink-Informations-Prozess(UIP)-Verfahren`
- Correct (with reference numbers): `Kopfrahmen-(110-)Winkelbewegungsrate` (hyphen after number in parentheses)

---

## 8. Compound Nouns & Hyphens

- **Compound nouns:** When multiple English nouns are strung together and the grouping is unclear, form a **long German compound noun** rather than risk a mistranslation.
  - EN: `access node control protocol partition` → DE: `Zugangsknotensteuerprotokollpartition`
- **Hyphens:** Use sparingly. Consistency is paramount — if you add a hyphen to one compound, you must do so for all similar compounds in the patent.
- **Loan words in compound nouns:** Hyphens are generally recommended.
  - DE: `Fed-Batch-Modus`

---

## 9. Consistency

- **One source term = one target term** throughout the patent, especially in claims.
- Consistency applies to syntactic constructions too: "configured to" → always "konfiguriert, um"; "for + infinitive" → always "zum + Infinitiv", etc.
- **Consistency with previously published claims:** Use the translated terminology from published claims in the description. If a term from the claims is not ideal but not objectively wrong, use it in the description with a "beziehungsweise" bridge on first mention:
  - Example: "Störgeräusch beziehungsweise Rauschen" (first instance); "Rauschen" thereafter.
- **Consistency with previously translated segments** in the same project: adopt and adhere to existing terminology; correct genuine errors but notify the PM.
- **Consistency trumps this Style Guide:** Stylistic changes for their own sake should be avoided in copy-editing — only implement if the translator's choice is objectively wrong.

---

## 10. EP Title & Document Handling

- Use the **title as published in the EP register** (check EPO website by application/publication number).
- If TIG and EP register titles differ → use EP register title.
- **Never change the published translated title** itself, even if you use different terminology in the translation.
- If the published title contains incorrect terminology → note it in the errata sheet; the client decides.
- **Amended claims/specifications:** Do not introduce changes beyond the amended portions. If you spot a significant error in the existing translation, notify the PM before making changes.

---

## 11. Noun vs. Verb Forms

| EN (source type) | DE (target type) |
|---|---|
| Noun (e.g., "separation") | Noun: **Trennung** |
| Gerund/verbal noun (e.g., "separating") | Nominalized verb: **Trennen** |

The noun form (Trennung = result/product) and the nominalized verb (Trennen = process) are not interchangeable in patent claims.
