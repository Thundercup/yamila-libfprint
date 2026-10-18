# Maintaining releases

Release packages are experimental and unsigned. Publish their matching source inputs, build records, checksums, notices and known limits. Hardware results must identify the tested scope; hosted compilation does not establish hardware acceptance.

## Prepare

1. Update both README languages, the support matrix and change log. Increment distribution package revisions when release contents change.
2. Run the allowlist/digest audit, documentation-link check and default synthetic checks. The vendor binary must retain its pinned identity and separate notice.
3. Commit a clean source snapshot and run the synthetic and package workflows for that exact commit. Use read-only workflow permissions and ordinary-user compilation.
4. Inspect the downloaded RPM/DEB payloads and scripts. Retain the Fedora SRPM and the Ubuntu project overlay plus full pinned upstream source archive. Keep each build record alongside its artifacts.
5. Create a prerelease tag for the tested commit, upload selected assets and SHA256SUMS, and verify the published asset identities. Do not upload build roots or private diagnostic data.

## Describe

Document supported systems/architectures, exact baseline requirements, package versions, unsigned status, automatic Ubuntu PAM behavior, opt-out/removal policy and unverified scenarios. Link the actual Actions runs and matching commit. State whether results were synthetic, container-based or hardware tests.

Checksums identify bytes; they do not establish a signing identity. A future signed repository must document key distribution and rotation without asking users to disable verification globally.
