# Operational Store documentation and release front-load contract

**Date:** 2026-08-16

**Product baseline:** `origin/main` at
[`3e6ae7f6157364eeedaa2667d2a1deabed9efcee`](https://github.com/spontain112/djsupport/commit/3e6ae7f6157364eeedaa2667d2a1deabed9efcee)

**Documentation baseline:** `djsupport-docs/main` at
[`70bfbab06e5d4a34d659bbc73e2145e8cc3f6898`](https://github.com/spontain112/djsupport-docs/commit/70bfbab06e5d4a34d659bbc73e2145e8cc3f6898),
with the unmerged production foundation at
[`58fd4013c43cf2da426c761e0f0e21e64a60e777`](https://github.com/spontain112/djsupport-docs/commit/58fd4013c43cf2da426c761e0f0e21e64a60e777)

**Scope:** Implementation research for
[#148](https://github.com/spontain112/djsupport/issues/148) and
[#149](https://github.com/spontain112/djsupport/issues/149), plus a downstream
authority audit of human-gated
[#150](https://github.com/spontain112/djsupport/issues/150) and
[#151](https://github.com/spontain112/djsupport/issues/151). No tag, GitHub
Release, package-index publication, workflow artifact upload, advisory
publication, live provider call, or owner-data access is authorized or
performed by this contract.

**Contract precedence:** The exact issue amendments are the proposed normative
execution delta; the preceding sections explain and source that delta. Once an
amendment is accepted into an issue, the issue body is authoritative. Do not
combine conflicting versions—reconcile the amendment first.

## Decision

The two independently safe front-load streams now stand at different stages:

1. establish a stable review route for the documentation foundation in
   [#116](https://github.com/spontain112/djsupport/issues/116), then prepare
   #148 as a **draft, unmerged** documentation change with the final
   information architecture, privacy inventory, contract tests, and visibly
   unresolved product-command slots; and
2. treat the reusable, publication-free candidate qualification harness as
   completed infrastructure: [#181](https://github.com/spontain112/djsupport/issues/181)
   was merged by [PR #182](https://github.com/spontain112/djsupport/pull/182) at
   this note's product baseline, without adding a version override, consuming
   release records, or uploading built archives.

Do not finalize #148 until #147 has frozen the public migration, recovery,
restore, and rollback behavior. Do not prepare or merge the exact version PR
for #149 until #136, #130, #132, #147, and #148 are complete. The existing
automated [PR #159](https://github.com/spontain112/djsupport/pull/159) currently
prepares final `0.7.0`, not `0.7.0rc1`; its current head is not a release
candidate and must not merge.

The remaining safe front-load work is therefore the draft documentation route.
The merged harness is a stable prerequisite, but its current evidence is
deliberately `synthetic_non_release`; it is not evidence that a 0.7 candidate
exists. This split advances reusable mechanics without turning planned behavior
into public instructions or confusing a mutable version branch with a frozen
candidate.

## Current-state evidence

### The repository boundary is decided but not integrated

The accepted #116 decision assigns behavior, domain language, commands,
release state, schemas, and architecture to `djsupport`; `djsupport-docs` owns
audience-focused explanation, navigation, and presentation. The proposed
product ADR records the same boundary
([ADR branch](https://github.com/spontain112/djsupport/blob/dcd0f163956f1ad27ee16a3d11ebac5132ec34f7/docs/adr/0004-separate-public-documentation-from-product-authority.md)).
The docs foundation implements it through a machine-readable product contract
and a read-only cross-repository check
([contract](https://github.com/spontain112/djsupport-docs/blob/58fd4013c43cf2da426c761e0f0e21e64a60e777/product-contract.json),
[checker](https://github.com/spontain112/djsupport-docs/blob/58fd4013c43cf2da426c761e0f0e21e64a60e777/scripts/check_product_contract.py)).

That foundation is not yet on `djsupport-docs/main`, and there is currently no
pull request or validation run for it. The default branch is still the
Mintlify starter. Consequently, #148 has two real prerequisites:

- #116 must first provide the production information architecture, ownership
  rules, and CI review route; and
- #147 must freeze the actual 0.7 command and recovery behavior that the guide
  will explain.

The product repository must not absorb the #148 prose as a workaround. Its
role is to expose canonical facts and verify documentation impact; the public
guide itself remains a `djsupport-docs` change.

### The release lane is not yet on a development version

Current product metadata still says `0.6.0`
([`pyproject.toml`](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/pyproject.toml)).
Issue [#136](https://github.com/spontain112/djsupport/issues/136) explicitly
requires a replacement 0.6 freeze plus separately authorized tag and final
GitHub Release before its draft development-version PR may merge. Under the
present publication exclusions, that human gate remains open.

The version workflow rebuilds the mutable `release/version` branch from each
push to `main`, consumes all pending release records, force-with-lease updates
that branch, and edits or opens its PR
([workflow](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/.github/workflows/version-pr.yml),
[preparer](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/scripts/release_records.py)).
Ten records are currently pending. Without a one-use
`.release-notes/next-version` override, automation has prepared `0.7.0` in PR
#159. That PR is an evolving projection of pending records, not a frozen
candidate.

The accepted release process already separates version preparation,
validation, tag creation, GitHub Release creation, and package publication
([release checklist](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/releasing.md)).
PEP 440 orders `.devN` before `rcN` and `rcN` before the corresponding final
release, so `0.7.0.dev0` -> `0.7.0rc1` -> `0.7.0` is the correct version
sequence
([PyPA version specification](https://packaging.python.org/en/latest/specifications/version-specifiers/#summary-of-permitted-suffixes-and-relative-ordering)).

### The merged harness is reusable infrastructure, not candidate evidence

Current CI runs the complete offline suite and compilation on Ubuntu with
Python 3.10 and 3.14, then builds and inspects one source archive and one wheel
and performs a clean wheel smoke install
([CI](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/.github/workflows/ci.yml)).
The SQLite delivery workflow separately verifies 25 exact APSW native cells
across Linux, macOS, and Windows, with read-only permissions and no artifact
upload
([native workflow](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/.github/workflows/sqlite-runtime.yml),
[delivery policy](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/sqlite-runtime-delivery.md)).

PR #182 added a read-only Candidate qualification workflow and versioned input
and evidence contracts. A full manual run binds every observed job to the exact
workflow/product commit, requires the exact current `djsupport-docs/main`
commit, pins build and documentation tools, rebuilds one reproducible DJ Support
wheel digest across all 25 qualified APSW cells, runs the documentation contract
and site checks, and emits one path-free evidence document. Dispatch inputs are
equality facts and never select executable checkout refs. Pull requests run only
the harness's synthetic contract tests
([candidate workflow](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/.github/workflows/candidate-qualification.yml),
[release guidance](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/releasing.md#publication-free-candidate-qualification)).

The merged finalizer intentionally accepts only `synthetic_non_release` with
`synthetic_contract` scenario evidence. It therefore does **not** yet prove all
of #149 on one exact merged candidate:

- the Operational Store Preview, cutover, interrupted resume, restore, rollback,
  and diagnostics behavior does not exist until #138–#147 and #132 merge;
- the synthetic scenario seam does not substitute for installed execution of
  those final product behaviors;
- the exact merged #148 documentation commit does not yet exist; and
- no merged `0.7.0rc1` product commit exists to qualify.

#149 must extend or feed the same versioned harness with observed installed
scenario results and admit `release_candidate` evidence only after those facts
exist. It must not weaken or replace the already merged identity, native-cell,
documentation, privacy, and no-publication gates.

PyPA distinguishes building distributions from uploading them: `python -m
build` produces an sdist and wheel, while upload is a separate step
([packaging flow](https://packaging.python.org/en/latest/flow/)). That supports
local and CI validation without package publication. GitHub Actions artifacts,
however, persist files for later download and are available to signed-in
readers of a public repository, ordinarily for up to 90 days
([workflow artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts),
[download and retention](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)).
Under the current exclusions, candidate archives should therefore be built,
verified, hashed, and deleted in-job rather than uploaded.

## Safe front-load stream A: documentation contract

### Work that is stable now

A draft #148 change may safely establish all of the following before #147:

- a versioned **Upgrade to 0.7** route in **Use DJ Support**;
- sections for release preflight, verified backup, migration Preview,
  explicit apply, interruption recovery, restore, and rollback;
- a privacy inventory covering the database, WAL and SHM sidecars, snapshots,
  backups, restore staging, diagnostics, query exports, retained legacy JSON,
  and reports;
- the statement that `.gitignore` is a repository guardrail, never permission
  to commit private data;
- the prohibition on credentials, local paths, playlists, library data,
  matching knowledge, and user-derived evidence entering Git;
- the separation of `config.json` and Spotipy-managed credentials from the
  Operational Store; and
- contract tests that require every section, classification metadata, and
  canonical source link.

The draft should update, at minimum:

- `use/upgrade-0-7.mdx` (new versioned guide);
- `use/upgrade.mdx` and `use/backup-and-restore.mdx` (navigation only until
  behavior freezes);
- `docs.json` (navigation);
- `product-contract.json` (versioned migration-contract facts);
- `scripts/check_product_contract.py` and its tests; and
- `.github/workflows/validate.yml` only where the stronger contract requires
  it.

The existing foundation already pins the Mintlify CLI and runs contract tests,
`mint validate`, `mint broken-links`, and `mint a11y`
([docs validation workflow](https://github.com/spontain112/djsupport-docs/blob/58fd4013c43cf2da426c761e0f0e21e64a60e777/.github/workflows/validate.yml)).
Mintlify documents `mint validate` as strict build validation,
`mint broken-links` as internal-link validation, and `mint a11y` as contrast
and alternative-text validation
([Mintlify CLI reference](https://www.mintlify.com/docs/cli/commands)). For
#148, also enable anchor and redirect checks, while validating canonical
product links against the checked-out product repository rather than relying
on a flaky general external-link crawl.

### Facts that must remain unresolved until #147

The draft must not invent or infer:

- command names, flags, prompts, exit codes, or example output;
- Operational Store filenames or application-data paths;
- the supported rollback duration or its start/end event;
- what an interrupted phase reports or which exact resume command follows;
- whether 0.7 is currently a candidate or a final stable release; or
- any screenshot based on owner data.

Use machine-detectable placeholders in the draft branch and make the contract
checker reject a `publishable` status while any placeholder remains. Keep the
PR draft and unmerged. Once #147 lands, fill the slots from executable `--help`,
public behavior tests, canonical product docs, and synthetic outputs on the
exact product commit. Do not copy internal schema or transaction explanations
into the public guide.

### Exact #148 amendment

Append this to #148:

```markdown
## Documentation foundation and two-phase delivery

The production docs foundation in #116 is an additional prerequisite. The
default branch of `spontain112/djsupport-docs` must first contain the accepted
Use/Build information architecture, canonical product-contract check, and
Mintlify validation workflow.

Phase A may begin after #116 has a stable review route: prepare a draft 0.7
guide, navigation, private-artifact inventory, and contract tests. Do not infer
commands, outputs, paths, recovery choices, or rollback duration, and do not
merge or publish placeholder guidance.

Phase B begins only after #147 freezes production behavior. Replace every
placeholder from executable CLI help, public behavior tests, and canonical
product sources; validate against that exact product commit; then run product
contract tests, `mint validate`, `mint broken-links --check-anchors
--check-redirects`, and `mint a11y`.

The final PR must record the exact product commit validated, contain no owner
data or owner-derived screenshot, and link back to this issue. Product behavior,
terms, commands, release state, schemas, and architecture remain canonical in
`djsupport`; `djsupport-docs` owns explanation and presentation.

## Blocked by

- #116
- #147
```

## Completed front-load stream B: candidate qualification harness

Issue [#181](https://github.com/spontain112/djsupport/issues/181), **Build the
publication-free 0.7 candidate qualification harness**, is complete through
[PR #182](https://github.com/spontain112/djsupport/pull/182). The following
ledger separates the reusable mechanism already merged from product behavior
that cannot exist until the Operational Store and documentation land:

1. **Merged—read-only authority.** Pull requests run only the synthetic contract
   tests. Full qualification is a manual `workflow_dispatch`; workflow
   permissions are `contents: read`, actions are full-SHA pinned, checkout
   credentials are not persisted, and secrets, write permissions,
   `continue-on-error`, publishing commands, and artifact upload are absent.
2. **Merged—exact source.** Executable product checkout is fixed to the workflow
   commit and compared with the expected full SHA. Canonical docs checkout is
   fixed to `djsupport-docs/main` and compared with the expected full SHA. Every
   observed job is bound to that product SHA and the exact workflow identity.
3. **Merged—exact build input.** Release-build tools are pinned, build isolation
   is disabled after explicit installation, and `SOURCE_DATE_EPOCH` derives from
   source history
   ([build documentation](https://build.pypa.io/en/latest/how-to/basic-usage.html#building-without-isolation),
   [SOURCE_DATE_EPOCH specification](https://reproducible-builds.org/specs/source-date-epoch/)).
4. **Merged—one package identity.** The harness verifies archive identity and
   rebuilds the pure-Python DJ Support wheel in every claimed native cell,
   requiring the canonical SHA-256 in all 25 observations.
5. **Merged—native runtime identity.** Every cell reuses #167's exact APSW
   artifact/runtime policy and rejects source-built fallback.
6. **Deferred to #149—installed product behavior.** The current scenario seam is
   explicitly `synthetic_contract`. After #138–#147 and #132, it must consume
   observed installed Preview, cutover, interruption, resume, backup, restore,
   rollback, and diagnostics results from invented data; static scenario facts
   cannot qualify a release candidate.
7. **Partly merged—cross-platform scope.** The full 25-cell matrix and installed
   wheel/runtime smoke are present. Actual installed Operational Store scenarios
   on native Linux, macOS, and Windows remain part of the #149 extension.
8. **Mechanism merged; exact input blocked—documentation identity.** The workflow
   can check one exact canonical docs commit and run its contract/site checks,
   but the final #148 commit does not exist yet.
9. **Merged foundation; final product inventory deferred.** The repository
   privacy and archive inspectors are required. #149 must extend their denylist
   for the final database, sidecars, snapshots, backups, restore staging,
   diagnostics, exports, and retained legacy state introduced downstream.
10. **Merged—ephemeral archives.** Evidence contains only bounded path-free facts;
    the workflow does not upload the source archive, wheel, database, logs, or
    other generated artifacts.

The merged harness fails closed on identity, version, changelog, tool, native
cell, wheel digest, docs commit, job/step, privacy, source-build, or publication
contract disagreement. It was verified with invented non-release facts and does
not claim that a 0.7 candidate exists.

## Exact #149 amendment

Replace #149's dependency and freeze language with the following:

```markdown
## Exact freeze definition

The candidate is the full merged `main` commit that contains package version
`0.7.0rc1` and the generated matching changelog entry. A `release/version` PR
head, passing run on another SHA, branch name, local checkout, or rebuilt
archive alone is not the candidate.

Before preparing version metadata:

- close #136 and confirm `main` is explicitly `0.7.0.dev0`;
- close #130, #132, #147, and #148; #131, #167, and #181 are satisfied
  infrastructure prerequisites;
- merge every intended 0.7 release record and audit its consumer-visible
  summary;
- record the exact merged `djsupport-docs` commit from #148; and
- extend the publication-free candidate qualification harness with the adapters
  that will consume observed installed results for the final Operational Store
  scenarios, and require its `synthetic_non_release` contract tests to be green.
  Do not require or emit `release_candidate` evidence before the rc metadata
  exists.

Only then add one-line `.release-notes/next-version` value `0.7.0rc1` through a
reviewed PR. Let automation regenerate the existing open `release/version` PR
from current `main`; verify it consumes exactly the intended records, changes
the project version to exactly `0.7.0rc1`, and creates exactly one matching
changelog section. The current `0.7.0` state of PR #159 is not acceptable and
must not merge.

After the version PR merges, run the finalizer in `release_candidate` mode and
rerun every required gate on the exact merge commit. Require the same DJ Support
wheel SHA-256 on all claimed native cells,
the exact qualified APSW artifact/runtime per cell, installed synthetic
Preview/cutover/resume/restore/rollback/diagnostics coverage, the exact #148
docs commit check, the full offline/privacy/package suites, compilation,
CodeQL, archive inspection, and clean installation. No skip, warning-only
result, `continue-on-error`, different SHA, or source-built fallback passes.

Record the evidence using the issue template below. Built archives are
validation-only: do not upload them to Actions, a GitHub Release, or a package
index. No tag, GitHub Release, package publication, advisory publication, live
provider call, or owner-data operation occurs.

## Blocked by

- #136
- #130
- #132
- #147
- #148
```

The explicit #136 dependency matters even though #138 already names it: #149
must prove that the release train began at `0.7.0.dev0`, not merely infer that
from downstream issue closure. Listing #147 explicitly makes the exact
behavior-freeze gate auditable rather than relying only on transitive blockers.

## Candidate evidence record

Post exactly one completion comment on #149 after the merged candidate has
passed. Use this schema and do not include local paths or raw logs:

```markdown
## Frozen DJ Support 0.7.0rc1 candidate

- Product commit: `<40-character merged main SHA>`
- Documentation commit: `<40-character merged djsupport-docs SHA>`
- Package metadata: `0.7.0rc1`
- Changelog: `[0.7.0rc1] - YYYY-MM-DD`
- Pending release records: `<none; README only>`
- Version PR: `<URL and head SHA>`
- Exact-merge CI: `<run URL and conclusions>`
- Exact-merge CodeQL: `<run URL and conclusions>`
- Candidate qualification: `<run URL; all native cells passed>`
- Documentation validation: `<run URL or exact in-run check>`
- Offline suite: `<test count, Python endpoints, passed>`
- Installed synthetic scenarios: `Preview, apply/cutover, resume, backup,
  restore, rollback, diagnostics — passed on Linux/macOS/Windows`
- DJ Support sdist: `<filename>`, `<size>`, SHA-256 `<digest>`
- DJ Support wheel: `<filename>`, `<size>`, SHA-256 `<one digest for every
  native cell>`
- APSW evidence: `<catalog version; 25/25 exact cells; no source build>`
- Archive/privacy inspection: `<member counts and passed categories>`
- Remote verification: `origin/main == <candidate SHA>` after validation
- Publication state: `no tag; no GitHub Release; no package upload; no Actions
  artifact upload; no advisory publication`
- Data/provider state: `synthetic only; no owner data; no live provider call`
- Handoff authority: `evidence only; no #150 tag, pre-release, asset, or package
  publication authorization is granted or implied`
```

The prior #134 completion comment is the project-owned precedent for recording
an exact commit, workflow URLs, suite results, archive member counts and
digests, and the fact that validation-only artifacts were not uploaded
([#134 evidence](https://github.com/spontain112/djsupport/issues/134#issuecomment-5304217325)).
For an eventual separately authorized release, GitHub's immutable-release
model can bind a tag, commit, and assets and prevent later asset/tag mutation
([GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases));
that future publication operation is deliberately outside #149.

## Downstream human gates: #150 and #151

The #149 completion comment is a **sealed evidence handoff**, not a release
instruction and not approval to exercise any publication capability. Issue
#150 is `ready-for-human` and owns the candidate tag and pre-release decisions;
#151 is `ready-for-human` and separately owns final promotion and return to
development. The agent-ready #149 lane must end before either begins.

GitHub Releases are based on Git tags and make software available to a wider
audience
([GitHub release model](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)).
The GitHub CLI will create a missing tag automatically unless the caller uses
an existing tag with `--verify-tag`; it also exposes independent
`--prerelease` and `--latest=false` controls
([`gh release create`](https://cli.github.com/manual/gh_release_create)). These
facts make three authorities materially separate: tag creation, GitHub Release
publication, and package-index publication.

### Exact #149 -> #150 handoff

Before #150 requests any human authorization, its owner must re-read #149 and
prove all of the following without changing remote state:

- the full product and docs SHAs still equal the frozen evidence;
- every cited workflow is green for that exact product SHA and has no skipped
  or allowed-to-fail required cell;
- candidate version, changelog, release-record consumption, sdist/wheel
  filenames, sizes, digests, and 25-cell runtime facts exactly match #149;
- `v0.7.0rc1` and a corresponding GitHub Release are absent;
- the current Latest final release is unchanged;
- no candidate archive has been uploaded to Actions, a Release, or a package
  index; and
- no new commit, vulnerability/revocation fact, docs drift, or blocking issue
  has invalidated the freeze.

Only after that read-only preflight may #150 request three independently
scoped approvals, in order:

1. create and push one annotated `v0.7.0rc1` tag at the exact #149 SHA;
2. after verifying the remote tag target, create one GitHub Release for that
   existing tag with **Pre-release = true** and **Latest = false**; and
3. publish to a package index only if separately requested and approved.

The Release operation must verify the existing tag rather than allow GitHub or
the CLI to create one implicitly. Any rebuilt sdist or wheel must reproduce the
#149 digest before it can be considered the same candidate. A mismatch creates
a blocking defect and a new candidate; it never authorizes replacing, moving,
or silently rebuilding the frozen identity.

After authorized publication, #150 downloads the published candidate artifacts
into disposable environments, verifies their digests against #149, and repeats
the synthetic migration/recovery/rollback/diagnostics exercise. This is
artifact-consumer validation, not permission for live Spotify/Beatport calls
or owner data. The Release must remain a pre-release and must not displace the
Latest final channel. GitHub documents both the Pre-release and Latest choices
as explicit release properties
([managing releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)).

Append this to #150:

```markdown
## Authority and evidence handoff from #149

#149 supplies evidence only. It does not authorize a tag, GitHub Release,
release asset, package upload, live-provider call, or owner-data operation.

Before requesting authorization, revalidate the exact #149 product/docs SHAs,
workflow conclusions, version/changelog state, archive identities and digests,
25-cell runtime evidence, absence of `v0.7.0rc1`, absence of its Release, and
unchanged Latest final release.

Request separate explicit approval for: (1) the annotated `v0.7.0rc1` tag at
the exact #149 SHA; (2) after remote tag-target verification, the GitHub
Release for that existing tag with Pre-release true and Latest false; and (3)
any package-index publication. The Release operation must verify the existing
tag and must not auto-create or retarget it.

Any rebuilt or downloaded candidate archive must match the #149 filename,
size, and SHA-256 before use. Exercise only disposable synthetic environments.
Any mismatch, failed gate, revocation, docs drift, or behavioral defect blocks
promotion and requires a new candidate; never mutate the frozen candidate.
```

### Exact #150 -> #151 handoff

Issue #151 cannot promote the rc1 tag or merely relabel the candidate Release
as final. It first consumes #150's evidence and defect list, resolves every
blocking issue through normal reviewed development, and prepares a distinct
final `0.7.0` version commit. If #150 found no defects, the final version-only
commit is still a new identity and must receive the complete final-release
validation on its own SHA.

The final lane must:

- record the exact proven rc1 tag, Release URL, artifact digests, installed
  synthetic results, and all issues opened by #150;
- prove each such issue closed or explicitly still blocking;
- prepare `0.7.0` and its changelog through a separately reviewed version PR,
  with the linked #148 docs commit and required notices unchanged or updated
  deliberately;
- repeat every #149 gate on the exact final merge commit, including package
  reproducibility, native APSW identity, installed synthetic behavior, docs
  validation, privacy, CodeQL, and archive inspection;
- obtain separate human authorization for the annotated final tag, then the
  Latest GitHub Release, then any package-index publication;
- verify published tag target, Release `isPrerelease=false`, Latest identity,
  asset digests, and clean installation; and
- only after publication verification merge a separately reviewed change to
  the next explicit `.dev0` version.

Append this to #151:

```markdown
## Final-promotion authority

#150 supplies a proven pre-release and a defect/evidence handoff; it does not
authorize final promotion. Do not relabel `v0.7.0rc1`, move its tag, or reuse
its commit as `0.7.0` without separately reviewed final version metadata and a
complete exact-final-SHA validation.

Record every #150 issue and require it to be resolved or explicitly blocking.
Prepare one exact `0.7.0` final commit with complete changelog, linked #148
documentation commit, and required notices. Repeat the full candidate-quality
gate on that exact final commit.

Request separate explicit approval for: (1) the annotated final tag at the
exact validated final SHA; (2) after remote tag-target verification, the final
GitHub Release with Pre-release false and Latest true; and (3) any package-index
publication. Verify tag, Release, asset digests, Latest state, and clean
installation before returning `main` to the next reviewed `.dev0` version.
```

Neither downstream amendment authorizes action now. They define the evidence
and approval boundaries that a future human-gated session must enforce.

## Dependency and concurrency map

```text
#116 docs foundation ───────────────┐
                                    ├─> #148 final docs ──┐
#136 0.6 publish + 0.7.dev0 ─> #138 ... #147 ───────────┤
                                                          ├─> #149 exact freeze
#130 Qualification deletion test <─ #147 ────────────────┤
#132 private diagnostics <────────── #147 ────────────────┘

#181 candidate harness (merged, synthetic_non_release) ──> #149 exact freeze
             #149 adds observed installed release-candidate scenario evidence

#149 evidence-only freeze -> #150 human tag + pre-release gate -> #151 human final + Latest gate
```

The #148 draft and completed #181 harness did not overlap: one changes only
`djsupport-docs`; the other changed release tooling/tests in `djsupport`. Final
#148 content waits on #147. #149 reuses the merged harness but must add observed
installed scenario evidence before it can admit `release_candidate`; actual
version preparation waits on every listed gate.

## Stop conditions

Stop and return to the owning issue rather than weakening a gate if any of the
following appears:

- #116 still lacks an integrated docs foundation or stable review route;
- any #148 placeholder remains, commands differ from the exact product build,
  or docs validation targets mutable product facts instead of the chosen
  commit;
- main is not `0.7.0.dev0` before the one-use candidate override;
- PR #159 still says `0.7.0`, consumes an unexpected record, lacks required
  checks, or is not fresh against `main`;
- a test is skipped, allowed to fail, or runs on a different SHA;
- any native cell produces another DJ Support wheel digest or an unqualified
  binding/runtime;
- package inspection finds a private/generated artifact or required public
  policy/notice is absent;
- evidence would require an artifact upload, tag, Release, package upload,
  advisory publication, owner data, or live provider call; or
- a #149 completion statement is treated as tag, GitHub Release, release-asset,
  or package-index authority rather than as evidence-only handoff;
- #150 attempts implicit tag creation, Latest candidate status, artifact
  replacement, or a digest mismatch; or
- #151 attempts to relabel rc1 as final, skips exact-final-SHA validation, or
  reopens development before final publication is verified; or
- a concurrent branch changes version automation, release records, docs
  ownership, #147 public behavior, or the candidate commit.

These are blockers to resolve, not reasons to narrow the candidate definition.

## Primary sources

### DJ Support and documentation sources

- [Issue #116 — documentation-site decision](https://github.com/spontain112/djsupport/issues/116)
- [Issue #136 — 0.6 publication/development gate](https://github.com/spontain112/djsupport/issues/136)
- [Issue #147 — retire JSON production writers](https://github.com/spontain112/djsupport/issues/147)
- [Issue #148 — migration/recovery guidance](https://github.com/spontain112/djsupport/issues/148)
- [Issue #149 — exact 0.7.0rc1 freeze](https://github.com/spontain112/djsupport/issues/149)
- [Issue #150 — human-gated candidate publication and exercise](https://github.com/spontain112/djsupport/issues/150)
- [Issue #151 — human-gated final promotion](https://github.com/spontain112/djsupport/issues/151)
- [Issue #181 — publication-free candidate qualification harness](https://github.com/spontain112/djsupport/issues/181)
- [PR #182 — merged candidate qualification implementation](https://github.com/spontain112/djsupport/pull/182)
- [Product release checklist at the inspected commit](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/docs/releasing.md)
- [Candidate qualification workflow at the inspected commit](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/.github/workflows/candidate-qualification.yml)
- [Release-record preparer at the inspected commit](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/scripts/release_records.py)
- [Version workflow at the inspected commit](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/.github/workflows/version-pr.yml)
- [CI at the inspected commit](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/.github/workflows/ci.yml)
- [SQLite native-delivery workflow at the inspected commit](https://github.com/spontain112/djsupport/blob/3e6ae7f6157364eeedaa2667d2a1deabed9efcee/.github/workflows/sqlite-runtime.yml)
- [Unmerged docs ownership ADR](https://github.com/spontain112/djsupport/blob/dcd0f163956f1ad27ee16a3d11ebac5132ec34f7/docs/adr/0004-separate-public-documentation-from-product-authority.md)
- [Unmerged docs validation workflow](https://github.com/spontain112/djsupport-docs/blob/58fd4013c43cf2da426c761e0f0e21e64a60e777/.github/workflows/validate.yml)
- [Unmerged docs product-contract checker](https://github.com/spontain112/djsupport-docs/blob/58fd4013c43cf2da426c761e0f0e21e64a60e777/scripts/check_product_contract.py)

### External specifications and first-party documentation

- [PyPA version specifiers](https://packaging.python.org/en/latest/specifications/version-specifiers/)
- [PyPA packaging flow](https://packaging.python.org/en/latest/flow/)
- [PyPA build basic usage](https://build.pypa.io/en/latest/how-to/basic-usage.html)
- [`SOURCE_DATE_EPOCH` specification](https://reproducible-builds.org/specs/source-date-epoch/)
- [GitHub workflow artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts)
- [GitHub artifact access and retention](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)
- [GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
- [GitHub release model](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [GitHub release management](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
- [GitHub CLI release creation](https://cli.github.com/manual/gh_release_create)
- [Mintlify CLI commands](https://www.mintlify.com/docs/cli/commands)
