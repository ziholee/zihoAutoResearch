# PyPI Trusted Publishing

The `Publish verified release to PyPI` workflow is disabled unless the repository
variable `PYPI_PUBLISH_ENABLED` is exactly `true`. Merging this workflow does not
create a PyPI project, configure a publisher, or upload any package.

## Verified publication

[Version 0.2.0 on PyPI](https://pypi.org/project/ziho-autoresearch/0.2.0/) was verified on 2026-10-13 KST.
[Run 38403802017](https://github.com/ziholee/zihoAutoResearch/actions/runs/38403802017)
passed release verification, protected environment approval and OIDC publication.
Both PyPI distributions match the original GitHub release SHA-256 values.
An isolated uv installation from production PyPI passed CLI help/list, complete
skill export byte comparison against the tag, and overwrite refusal.
The GitHub release and tag were not rebuilt or replaced during that verification.
The later privacy cleanup rewrites historical tags and withdraws old source
distributions. Those historical releases must not be retried or republished;
use a newly verified release such as v0.2.1.

## Maintainer setup

Complete these account settings separately before enabling publication:

1. Merge `.github/workflows/pypi.yml` and its verification scripts into `dev` and
   make the workflow available on the repository's default branch for manual
   dispatch. New release tags must contain this workflow and the verification
   scripts.
2. Create the GitHub environment **`pypi`** in **`ziholee/zihoAutoResearch`**.
   Configure required reviewers and deployment branch/tag rules that allow
   `dev` for a manual retry and intended `v*` release tags. Reviewers should inspect
   the verification job and the exact release before approving publication.
   The YAML references the environment but cannot configure its protection rules.
3. On PyPI, register a Trusted Publisher for project **`ziho-autoresearch`** using
   owner **`ziholee`**, repository **`zihoAutoResearch`**, workflow filename
   **`pypi.yml`** (not its full path), and environment **`pypi`**.
   For a project that does not yet exist, use a pending publisher; for an existing
   project, use its Publishing settings. Project ownership/name availability and
   successful publisher registration must be checked by the maintainer.
4. Set repository Actions variable **`PYPI_PUBLISH_ENABLED=true`** only after the
   publisher and environment protections are ready. Do not add a PyPI API token.

See the official [PyPI publisher setup guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/),
[pending publisher guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
and [PyPA publishing action](https://github.com/pypa/gh-action-pypi-publish).

## Release and retry

Follow [the release checklist](releasing.md) to produce the draft release. Its
assets must be exactly one wheel, one `.tar.gz` source distribution, and
`SHA256SUMS`. After review, publish the stable GitHub release. This fires the PyPI
workflow when it is enabled. Drafts and prereleases are not published to PyPI.

For a retry, select **Run workflow**, choose branch **`dev`**, and enter the exact
published tag, for example `v0.2.1`. Arbitrary workflow refs, branch names as tags,
prerelease versions, and unpublished releases are rejected. The tag must resolve
to a commit in `dev` history. Manual dispatch looks up the existing release;
it does not create a release or rebuild its assets.

The read-only verification job validates the release identity, asset inventory,
strict SHA-256 manifest, tag/version, metadata, runtime and skill bytes against
the tagged source. It also runs the installed-package scenarios. Only the wheel
and source distribution are transferred to a fresh publishing job by an immutable
Actions artifact ID; `SHA256SUMS` is excluded from the upload directory. The
publishing job has no checkout or package execution and is the only job with
`id-token: write`. It uses the protected `pypi` environment and PyPI's short-lived
OIDC authentication; [PyPI explains this flow here](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

The PyPA action creates attestations and uses `skip-existing: false`. A retry
fails if files already exist on PyPI. After a partial upload, inspect the actual
PyPI files before deciding the recovery; do not silently skip or replace them.
PyPI does not permit replacing an already uploaded filename.

Keep release tags protected against movement and review changes to publishing
workflows. SHA-256 checksums detect changed bytes relative to the manifest; they
are not an independent signature of who built the release. The workflow also
checks source equality, but repository, release, and environment access remain
part of the trust boundary.

## Verification limits

Local unit tests exercise invalid release state, unsafe and duplicate checksum
entries, missing/extra/corrupt files, tag mismatch, and source/wheel drift. The
installed-package gate checks distribution behavior. The v0.2.0 manual retry verified environment approval, OIDC exchange and real
PyPI upload after initial registration failures. A successful run does not
guarantee future releases: each requires its own verification and approval.
When `invalid-publisher` occurs, inspect the saved publisher on production PyPI;
GitHub environment setup alone does not register a PyPI publisher. If temporary
Actions artifacts have expired, manually dispatch from dev only for a release
whose tag and complete verified assets remain intact. Withdrawn historical
releases are not retry targets.
