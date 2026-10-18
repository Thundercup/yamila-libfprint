# Support and validation

The supported reader is **USB 2808:06fc, bcdDevice 0x2003**. Only x86_64/amd64 is targeted. Observations below are limited tests, not statistical accuracy or production acceptance.

| Area | Scope | Evidence |
| --- | --- | --- |
| Fedora baseline | Fedora 44, libfprint 1.94.100-1.fc44, fprintd 1.94.5-5.fc44, targeted SELinux policy 44.11-1.fc44 | Native development package tested; exact dependency gate |
| Fedora enrollment/persistence | Native FpPrint enrollment and daemon restart/reload | Passed on one device |
| Fedora verification | Enrolled finger match; one unenrolled-finger rejection | Passed; no accuracy estimate |
| Fedora lifecycle | Waiting-stage cancellation/recovery, exclusive clients, release/handoff, disconnected-owner recovery | Passed |
| Fedora authentication | Uncached sudo fingerprint and no-touch password fallback | Passed |
| Fedora desktop | KDE management, lockscreen and administrator authorization | Reported working |
| Hardening | Dedicated worker account, empty supplementary groups, zero effective capabilities, NNP/MDWE, core=0; Fedora SELinux Enforcing | Checked in finite test windows |
| Ubuntu baseline | Ubuntu 26.04 amd64, exact fprintd/libfprint versions and native unit digest recorded per build | Package baseline and integrity checked on reported installation |
| Ubuntu desktop | GNOME fingerprint setup and lockscreen | Reported working |
| Ubuntu authentication | sudo fingerprint, Polkit fingerprint, no-touch password fallback after enabling the distro PAM profile | Remote test report passed; existing Unix/SSS chain retained |
| Ubuntu automatic setup | Initial enable, idempotent reinstall, legacy upgrade/downgrade, preexisting preference, administrator edits, abort-remove recovery | Eight rootless-container transaction scenarios passed; new public-package installation on hardware not yet accepted |
| Package checks | Contents, script syntax, dependencies, fixed DLL, private library paths, no ELF RPATH/RUNPATH | Automated checks |
| Reproducibility | Two historical full RPM/SRPM builds in an independent signed-RPM userspace | Byte-identical for those fixed inputs; not a general claim for every later release |
| Clean-system lifecycle | Booted clean-system install/upgrade/downgrade/removal, service triggers and MAC labels | Not fully validated |
| CI | Synthetic checks and Fedora/Ubuntu package builds | See the repository Actions runs for the exact commit; CI does not test hardware |
| Signing | Development packages | Unsigned; SHA256SUMS is provided |

The private library registers only this Yamila driver. Other readers/revisions, identify, on-device storage, cross-finger duplicate detection, boot-login acceptance, image-transfer interruption, unplug/suspend/resume, multiple users/seats and long-term reliability are not claimed.

Native RAW FpPrint records are not additionally encrypted by the driver. On the checked Fedora installation, root owns the store, parent directories are 0700 and the template file is 0644 with fprintd_var_lib_t. Confidentiality depends on directory/MAC isolation. Existing encrypted stores from other integrations are not migrated or deleted.

Later package revisions can change documentation and packaging without new hardware acceptance. Use each package's build record and corresponding source; do not substitute a historical SRPM for a newer binary.
