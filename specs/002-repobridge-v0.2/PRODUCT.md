# RepoBridge — Product Vision

**Status:** written after v0.1 shipped and deployed, before feedback returned.
Deliberately flexible. Sections marked **[GATED]** must not be built until the
condition stated is met.

This document is about *what RepoBridge is for*. The specs describe what it does.

---

## 1. The problem, precisely

An LLM asked about a GitHub repository produces one of these:

1. **A refusal** — it cannot fetch the URL.
2. **A README summary** — it read one file and describes the project as that file
   advertises it, which is marketing copy, not structure.
3. **A prior-driven summary** — it recognises the repository name from training data
   and describes what it remembers, possibly years stale.
4. **A partial-but-unlabelled summary** — it read some files and summarised as though
   it read all of them.

**The reader cannot tell these apart.** All four produce fluent, confident,
plausibly-structured prose. The failure is invisible at the point of use and only
surfaces later, when a decision made on that summary turns out to be wrong.

This is not a capability gap. Models are good at summarising code they can see. It is
an **accountability gap**: no part of the output tells you what it was built from.

## 2. The promise

> RepoBridge never claims to have read something it didn't.

Operationally, four guarantees:

1. **Every entry is accounted for.**
   `total_entries == directories + selected + skipped + failed`, verified from stored
   rows rather than from a count that could drift and self-certify.
2. **Every omission has a reason.** A closed enum of machine-readable codes plus a
   specific human message. Not "some files were skipped."
3. **Every summary states its own coverage**, in its own prose, with figures drawn
   from provenance computed *before* the model was called.
4. **Every partial view says it is partial**, in the sentence a person actually
   reads — not only in a field they would have to know to look for.

The fourth guarantee is the one that keeps being violated in subtle ways and keeps
having to be re-fixed. It is the hardest to hold and the most valuable.

## 3. Who this is for

**Primary: an engineer meeting an unfamiliar codebase.** Evaluating a dependency,
onboarding to a repo, reviewing an open-source project before adopting it, or
deciding whether a library does what its README claims. They need to know what the
thing *is*, and they need to know when the answer is thin.

**Secondary: an LLM that needs repo context it can cite.** This is the direction
that makes RepoBridge infrastructure rather than a destination — see §5.

**Explicitly not for:** people who want a fast answer and do not care about its
provenance. They are better served by existing tools and RepoBridge will feel slow
and pedantic to them. That is a deliberate trade, not a defect to design away.

## 4. What v0.1 proved

- The accounting identity holds at scale — 37,393 entries on
  `kubernetes/kubernetes`, verified independently of the flag the API reports.
- Grounding survives adversarial checking: 65 claims across six live summaries
  audited against the chunks the model actually saw, zero hallucinated files.
- The model will decline rather than pad. Asked about a one-file repository with no
  mechanical limitation forcing a caveat, it wrote that it could not further
  characterise the project.
- **Grounded is not the same as representative.** The `psf/requests` finding (see
  `HANDOFF.md` §6.1) established that a summary can be factually impeccable and
  materially misleading if the sample it drew from was unrepresentative. This is the
  most important thing v0.1 learned and it constrains every future sampling decision.

## 5. Where this goes — MCP as the primary direction

**The thesis:** RepoBridge's value is not the web UI. It is a *guarantee* that any
LLM client could consume. An MCP server exposing the pipeline as tools makes
RepoBridge infrastructure — the thing that sits between an LLM and a repository and
refuses to let it bluff.

**Why it is the strongest direction:**

- **Nothing equivalent exists.** There are repo-reading tools. There is no repo-
  reading tool that hands back a provenance object the client can check.
- **Architecturally close.** The API is already the tool surface. Provenance is
  already structured. The run model already fits tool-call semantics.
- **It inverts the quota problem.** The client brings its own model, so RepoBridge
  stops paying for summarisation entirely. The Gemini daily limit — currently the
  binding constraint on everything — largely disappears.
- **It sidesteps the multi-user problem.** MCP servers run locally with the user's
  own credentials in the client config. No auth to build, no key management, no
  shared database.

**The tool surface, provisionally:**

| Tool | Returns |
|---|---|
| `analyze_repository` | run id, counts, the accounting identity, what was skipped and why |
| `list_repository_files` | classified entries, filterable by status/reason/path |
| `get_file_content` | extracted text for a path, or an explicit reason it is unavailable |
| `get_repository_summary` | the grounded summary with its provenance |
| `get_repository_diagnostics` | the stage timeline |

**The design constraint that makes it RepoBridge rather than a wrapper:** every tool
response must carry its own provenance. A client calling `list_repository_files` with
a filter must be told the unfiltered total. A client calling `get_file_content` on an
unread file must get a reason, not an empty string. The failure mode to design
against is a model receiving a partial result and reporting it as complete — which is
exactly the failure RepoBridge exists to prevent, one layer up.

## 6. Language coverage — a prerequisite, not a pivot

Kubernetes reports **17,167** files as `unsupported_extension`, essentially all Go.
Same for Rust, Java, Ruby, C++, C#, PHP.

A Go developer who tries RepoBridge concludes it does not work, because for them it
does not. This is not a pivot and it is not exciting, but it gates everything: nobody
will use an MCP server that cannot read their repository.

The work is mostly cheap — extraction for most languages is "read the text," which
the pipeline already does. The real questions are which languages, and whether
language-specific structure (imports, definitions) is worth extracting beyond raw
text. Default answer: raw text first, structure only where measurement shows it helps
summary quality.

**A caution carried from `psf/requests`:** widening the supported set changes which
files a capped run reads. Ranking must be re-checked, not assumed to still hold.

## 7. Private repositories **[GATED]**

**Gate:** `spec.md` records that Google's free tier permits using submitted prompts
for model training. This is acceptable for v0.1 *only because* it is public-repos-
only. **Before the first private repository is read**, summarisation must move to a
paid tier with training disabled, or to a different provider.

This is written down as a blocking prerequisite in the spec and must not be worked
around. A private repo read on a training-enabled free tier is a breach of user trust
that no amount of later correction fixes.

Beyond the provider question, private repos need per-user GitHub credentials, which
means auth, which means §8.

## 8. Multi-user / SaaS **[GATED]**

**Gate:** do not build until someone asks to pay, or the equivalent — a user
repeatedly hitting the shared instance's limits and asking for their own.

Every hard part of this (auth, per-user secrets, Postgres, billing, isolation) is a
hard part of *any* SaaS and none of it is RepoBridge-specific. Building it before
demand is confirmed spends months on the least differentiated work in the project.

Note also that MCP substantially reduces the need for it: an MCP server runs locally
with the user's own keys, which is multi-user without a multi-user system.

## 9. Non-goals

Carried from v0.1 and still true:

- A universal crawler, or a browser-automation system
- An IDE, or a code-editing tool
- A full static-analysis engine — RepoBridge reports what a file *is*, not what it
  *does*
- A chat interface over a repository. The summary is a single grounded artifact; a
  conversational layer would reintroduce every problem the provenance model solves
- A general-purpose LLM gateway

## 10. Success, defined honestly

**v0.1 succeeded** at proving the pipeline works and the guarantee holds. That is
already true regardless of adoption.

**The next thing to prove is that anyone wants the guarantee.** The feedback round
is the test. The signal to watch is not "this is cool" — it is someone noticing the
coverage disclosure unprompted, or telling you a summary would have misled them if it
hadn't been there.

**If the answer is that nobody cares about provenance**, that is a real result and
worth accepting rather than explaining away. The honest response would be to
reconsider what RepoBridge is for — possibly a repo browser with good diagnostics,
which is a smaller but genuine product — rather than to build more of something
nobody asked for.

## 11. Open product questions

- Does the coverage disclosure change behaviour, or do people read past it?
- Is "grounded but possibly unrepresentative" a distinction users can hold, or does
  it collapse to "trustworthy" in practice?
- Is the read cap a limitation to remove or a feature to make visible? Reading
  everything is expensive; reading a representative sample and saying so may be the
  better product.
- Does anyone want the diagnostics timeline, or is it engineering satisfaction?
- Is the right unit a *repository*, or a *question about a repository*?
