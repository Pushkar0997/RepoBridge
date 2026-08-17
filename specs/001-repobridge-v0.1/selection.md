# RepoBridge v0.1 — File Selection Rules

Extracted from `spec.md` section 7.3 on 2026-08-17. That section had accumulated a supported
list, a deliberately-not-supported list, a precedence order and two amendments, and had grown
several times longer than any of its siblings. It now lives here; `spec.md` section 7.3 keeps
the requirement and points at this file.

**Authoritative for:** which files RepoBridge reads, which it skips, and why. Implemented by
`src/repobridge/core/selection.py` (rules) and `src/repobridge/config.py:SelectionConfig`
(data and thresholds). Evaluated by `evals.md` Milestone 3; measured by `smoke.md`.

Nothing in this file was rewritten during the move. Both amendments are preserved verbatim
and dated.

---

## 1. Statuses

Every **file** entry is classified into exactly one status:

- **selected** — a supported readable file.
- **skipped** — unsupported or obviously non-readable, always with a reason.
- **failed** — an error during retrieval or parsing, including a tree entry too malformed to
  classify.

**Directories are counted, not classified.** Classification answers "will we read this file's
content?", which is not a meaningful question about a directory, and counting them as skipped
would make the skip totals misleading to a human reading diagnostics. They remain accounted
for by the identity:

```
total_entries == directories + selected + skipped + failed
```

The API returns this as `accounts_for_every_entry`. **No entry may vanish** — this is the
product's core promise, stated as an equation so it can be tested rather than asserted.

---

## 2. Supported types

*(widened 2026-08-17 — see the amendments in section 5)*

- **Prose and docs:** `.md`, `.markdown`, `.rst`, `.txt`
- **Code:** `.py`, `.js`, `.ts`, `.sh`, `.bat`
- **Notebooks:** `.ipynb`
- **Structured config:** `.json`, `.yml`, `.yaml`, `.toml`, `.cfg`, `.cnf`, `.ini`, `.in`
- **Template variants:** `.example`, `.template`, `.sample` — a config file committed in
  placeholder form (`.env.example`, `config.yml.template`) is text by construction and is
  often the only committed form of that config.
- **Recognised files matched by exact filename:**
  `Dockerfile`, `Makefile`, `Rakefile`, `Vagrantfile`, `Procfile`, `Gemfile`, `Pipfile`,
  `LICENSE`, `LICENCE`, `COPYING`, `NOTICE`, `AUTHORS`, `CONTRIBUTORS`, `README`,
  `CHANGELOG`, `CODEOWNERS`, `.gitignore`, `.gitattributes`, `.gitmodules`,
  `.git-blame-ignore-revs`, `.dockerignore`, `.editorconfig`, `.coveragerc`, `.flake8`,
  `.pylintrc`, `.npmrc`, `.nvmrc`, `.python-version`, `.ruby-version`, `.tool-versions`,
  `.prettierrc`, `.eslintrc`, `.babelrc`, `.browserslistrc`, `py.typed`, `.nojekyll`

Extensions are matched case-folded. Filenames are matched case-folded too — `dockerfile` and
`Dockerfile` are both legal and mean the same thing. Directory names are **not** case-folded;
see the recorded decision in `plan.md` under Milestone 3 for why that asymmetry is deliberate.

---

## 3. Skip reasons

A closed enum. Each code corresponds to a distinct *decision mechanism* — path position,
entry type, filename, extension, or size — not a synonym for another code. Every skipped file
carries the code **and** a specific human-readable message: the code lets diagnostics say
"9 non-text, 3 too large", the message tells a person why this particular path was skipped.

| Code | Mechanism | Covers |
|---|---|---|
| `excluded_directory` | path segment | vendored, generated and tooling directories (`node_modules`, `vendor`, `dist`, `.git`, `__pycache__`, …) |
| `submodule` | entry type `commit` | git submodules, whose contents live in another repository |
| `lockfile` | exact filename | generated dependency lockfiles |
| `non_text_asset` | extension | images, archives, media, fonts, compiled artifacts, databases, and `.svg` |
| `unsupported_extension` | extension / filename | not recognised. *Unknown*, not necessarily junk |
| `too_large` | size vs threshold | over `max_file_bytes`, despite being a supported type |

`lockfile` is load-bearing rather than cosmetic: `package-lock.json` is valid `.json`, a
*supported* type, so without its own rule a large generated file would be selected as content.

`non_text_asset` was named `binary_extension` until 2026-08-17. It was renamed because `.svg`
belongs to it and SVG is text — the code claimed something false. Nothing outside the
repository depended on the old name: there was no persistence layer, and no external
consumers.

### Deliberately not supported

Recorded so each exclusion is a decision rather than an oversight:

- **Source in languages beyond Python/JS/TS** (`.go`, `.rs`, `.java`, `.rb`, `.c`, `.cpp`,
  `.cs`, `.php`, …). Adding them is a scope increase, not a bug fix; a Go repository will
  legitimately report most of its source as `unsupported_extension` until a later version
  widens this.
- **`.csv`, `.tsv`, `.parquet`** and similar data files — tabular rows are neither prose nor
  structure, and a moderately sized CSV consumes context budget without explaining anything.
- **`.html`, `.css`** — presentation, and frequently generated.
- **`.xml`** — dominated by build output and generated descriptors; the genuinely useful cases
  (`pom.xml`) do not justify pulling in the rest yet.
- **`.svg`** — a judgement, not an omission. SVG is XML text, so it could be read, but
  committed SVGs are overwhelmingly machine-generated export artifacts whose content is path
  coordinates. That content costs context budget and explains nothing about a repository.
  Classified under `non_text_asset`. Revisit if hand-authored SVG proves valuable.

---

## 4. Rule precedence

Checked in this order. The order is chosen so the reported reason is the most informative
*true* one, and it is tested rather than incidental.

| # | Condition | Outcome |
|---|---|---|
| 1 | malformed entry (no usable path, or unrecognised type) | `failed` |
| 2 | entry type `tree` | directory — counted, not classified |
| 3 | entry type `commit` | `skipped` / `submodule` |
| 4 | any path segment is an excluded directory | `skipped` / `excluded_directory` |
| 5 | filename is a known lockfile | `skipped` / `lockfile` |
| 6 | extension is a known non-text asset | `skipped` / `non_text_asset` |
| 7 | extension **and** filename both unrecognised | `skipped` / `unsupported_extension` |
| 8 | supported, but over the size threshold | `skipped` / `too_large` |
| 9 | otherwise | `selected` |

**Position beats type beats name beats extension beats size.** Two consequences worth stating
explicitly:

- A `.py` inside `node_modules/` reports `excluded_directory`, not `unsupported_extension` —
  it is skipped for being vendored, which is the more useful fact.
- Size is checked **last**, so `too_large` means *"we would have read this, but it is too
  big"* rather than doubling up on files already skipped for another reason. An oversized
  `.png` reports `non_text_asset`.

Thresholds live in `config.py:SelectionConfig` (`max_file_bytes`, default 1,000,000) rather
than in the rules, per `AGENTS.md`: config, not hardcoded.

---

## 5. Amendments

Both preserved verbatim from `spec.md` section 7.3.

### Amendment — 2026-08-17: supported list widened

**Trigger.** A live smoke run of the Milestone 3 classifier against `psf/requests` returned
**78 skipped of 153 entries, 72 of them `unsupported_extension`**. The skipped set was `.yml`,
`.toml`, `.cfg`, `.rst`, `.in` and extensionless dotfiles — all readable text, much of it the
repository's configuration and prose. `evals.md` Milestone 3 requires that "no important
readable files are accidentally excluded", so the original list failed its own eval on a
mainstream Python repository.

**What changed.** The original list (`.md`, `.markdown`, `.py`, `.ipynb`, `.json`, `.txt`,
optionally `.js`/`.ts`) was written for prose, code and notebooks and omitted the
configuration layer entirely. It now covers structured config, reStructuredText, shell
scripts, template variants, and a closed set of recognised extensionless filenames.

**What did not change.** The skip rules. Lockfiles, vendored directories, binaries and the
size threshold are unaffected — this widened what counts as readable, it did not weaken what
counts as junk. `package-lock.json` is still skipped as a lockfile despite `.json` being
supported.

**Why filenames as well as extensions.** `Dockerfile`, `Makefile` and `.gitignore` carry real
signal about how a project builds and runs, and none of them has an extension. Matching them
by exact name keeps the rule closed and predictable; anything extensionless that is *not* on
the list is still skipped, and says so by name.

### Amendment — 2026-08-17 (second pass): residue swept

**Trigger.** After the first amendment, `psf/requests` still reported 23
`unsupported_extension` of 153 entries. Enumerating them individually — rather than accepting
the count — showed that most were correctly skipped, but a handful were excluded by *omission*
rather than by decision. `evals.md` Milestone 3 requires that no important readable file is
*accidentally* excluded; accidental is precisely the distinction.

**Added: `.cnf`.** OpenSSL configuration files (4 in the residue). Plain-text `key = value`
config, structurally identical to `.ini` and `.cfg`, both already supported. Excluding it
while supporting its near-identical siblings was an oversight.

**Added: `.bat`.** Windows batch scripts (`docs/make.bat` in the residue). `.sh` is already
supported, and `.bat` is its direct counterpart — the same build or documentation command,
written for the other platform. Excluding one while supporting the other was **asymmetry, not
judgement**: there is no reading of "readable text" under which a shell script is content and
a batch script is not. On a Windows-developed repository the `.bat` file may be the *only*
committed form of the build entry point.

**Added: `py.typed` and `.nojekyll`, by filename.** Both are zero-byte marker files whose
*existence* is the signal: `py.typed` (PEP 561) declares that a package ships type hints,
`.nojekyll` tells GitHub Pages not to run Jekyll. The decision is to **support** them rather
than improve their skip message. Classification answers "is this part of the repository's
readable inventory?", and for a marker file the answer is yes — a reader scanning the selected
list learns something real from seeing `py.typed` there. The cost is one empty file at
extraction; the alternative was to skip them under a code reading `unsupported_extension`,
which is simply the wrong description of a file that is not unsupported but empty. Matched by
exact filename, so the closed set stays tight — a `.typed` extension is *not* broadly
supported.

**Checked and deliberately left skipped.** The remaining residue after this amendment is 16
entries, every one of them a decision rather than an omission:

- 14 credential-shaped files (`.key` ×4, `.csr` ×3, `.pem` ×3, `.crt`, `.srl`, and two
  extensionless files named `ca`). These are TLS test fixtures. They stay skipped, and are the
  subject of the deferred `CREDENTIAL_LIKE` proposal in `plan.md` — the open question is how
  to name them, not whether to read them.
- `.css` and `.html`, already recorded above as deliberately not supported.

Driving the count to zero was not the goal. The goal was that every remaining exclusion be
traceable to a decision written down somewhere.

---

## 6. Open items

Recorded elsewhere, listed here so this file is a complete entry point to the rules:

- **`CREDENTIAL_LIKE` skip reason** — proposed, not built. `plan.md`, Milestone 3, "Candidate
  for a later milestone". Cannot be settled before file content is retrievable (Milestone 5),
  because a path alone cannot distinguish a test fixture from a real secret.
- **Directory matching is case-sensitive while filenames fold** — deliberate. `plan.md`,
  Milestone 3, "Recorded decision".
- **Zero-byte selected files** (`py.typed`, `.nojekyll`) will reach extraction with no
  content. Milestone 5 should decide whether that yields zero chunks or one empty chunk.
