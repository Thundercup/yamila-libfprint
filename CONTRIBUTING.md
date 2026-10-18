# Contributing

Keep changes within the documented hardware and package boundary. Protocol, template schema, DLL identity, isolation and installation-policy changes need focused evidence. Do not add a PID or claim another reader works from a shared vendor ID.

Use synthetic fixtures and the virtual driver in public tests. Never commit real fingerprint images/templates, USB captures, keys, machine logs or passwords. Vendor code remains separately identified in [the notice](vendor/LICENSE-NOTICE.md); do not replace it or apply the project license to it silently.

## Local checks

```sh
python3 -B tools/audit.py --write-manifest
python3 -B tools/release_check.py
python3 -B tools/build.py --upstream-archive /path/to/libfprint-v1.94.100.tar.gz --test-mode
python3 -B tools/check.py
```

Refresh a manifest only after reviewing intended edits. Add new public files explicitly to `public-files.json`; the auditor will not discover/authorize them automatically. A non-default build directory must also be passed to `tools/check.py --build-dir`.

## Synthetic CI

The workflow uses a GitHub-hosted Ubuntu runner with a Fedora 44 container. It installs compilation/test dependencies, then runs project checks as an ordinary builder account. Checkout v7 (Node 24, hosted runner version 2.327.1 or later) is pinned to a full commit, credentials are not persisted and the workflow has read-only contents permission. It does not use a self-hosted runner, request secrets, install the driver, enable hardware access, run the real vendor DLL or publish artifacts.

Fedora container tags and dependency repositories can move. This workflow checks synthetic compilation and source boundaries; it is not the version-locked release RPM builder or clean-system installation acceptance. The complete Fedora RPM lock remains in [packaging](packaging/fedora44-build.lock.json).

Public CI is configured for pushes, pull requests and manual runs. Check the workflow run and commit before relying on a result. GitHub guidance: [secure workflow use](https://docs.github.com/en/actions/reference/security/secure-use).

## Reviews and reports

Describe the trigger, resulting behavior, focused validation and remaining limits. Use the issue forms for minimal non-biometric reports. Do not request large private evidence uploads as a first response; ask for one relevant error/status and version tuple first.
