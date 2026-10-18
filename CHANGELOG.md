# Change log

## 0.0.1-preview.2 — 2026-10-18

- Welcome community testing on other x86_64 distribution releases and derivatives; build/test baselines are no longer installation whitelists.
- Replace OS/package-version and Ubuntu native-unit digest refusal with visible compatibility warnings.
- Remove exact runtime version pins while retaining generated ELF dependencies, required packages, architecture and integration/conflict checks. Build inputs remain pinned for reproducibility.
- Fedora package revision 11; Ubuntu package revision 4. No new hardware-compatibility claim.

## 0.0.1-preview.1 — 2026-10-18

- Initial community preview for USB 2808:06fc revision 0x2003 on Fedora 44 x86_64 and Ubuntu 26.04 amd64.
- Native fprintd integration through a private libfprint backend, dedicated broker/worker account and fixed proprietary vendor engine; no Wine runtime.
- Asynchronous enrollment/verification, waiting-stage cancellation, client ownership and disconnected-client recovery.
- Fedora package-owned SELinux policy, retained MDWE/NNP and zero core limit; no Fedora PAM/authselect edits.
- Ubuntu automatic distro fingerprint PAM setup with password/profile preservation, administrator-choice tracking and conditional removal/downgrade rollback.
- English and Simplified Chinese documentation, support matrix, issue forms and synthetic/package workflows.
- Public package revisions: Fedora 0.0.1-10.fc44; Ubuntu 0.0.1-3ubuntu26.04. Historical development validation is separately scoped in the support matrix.

Full clean-system lifecycle, power/multiuser reliability and boot-login acceptance remain outside this preview's validation.
