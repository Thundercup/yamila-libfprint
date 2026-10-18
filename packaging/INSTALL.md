# Fedora development RPM

Target: Fedora 44 x86_64, USB 2808:06fc / revision 0x2003. The initial package requires **libfprint 1.94.100-1.fc44, fprintd 1.94.5-5.fc44 and targeted SELinux policy 44.11-1.fc44**. An unvalidated update is refused rather than silently using a different baseline. This is an unsigned development artifact. Independent signed-RPM userspace builds, actual native-service hardening/SELinux and limited hardware checks have passed on one existing machine: enrollment/reload, waiting cancellation/recovery, one positive/negative verification and sudo/password fallback. Final-package clean-system installation/upgrade/downgrade/removal is not fully validated. See the [support matrix](../docs/SUPPORT.md); this is not broad installation or production acceptance.

## Package layout

The system libfprint and fprintd packages remain installed. The patched library is private at `/usr/lib64/yamila-fprint/`, and a package-owned fprintd drop-in sets `LD_LIBRARY_PATH` only for the native daemon. There is no global library replacement, ld.so configuration or alternate D-Bus gateway. This library enables only the supported Yamila driver; other readers are outside this preview's scope.

Runtime code, native guard/worker and the included vendor DLL live under `/usr/libexec/yamila-fprint/`. Files are root-controlled; the algorithm worker uses the dynamically allocated `yamila-fprint` account, a private primary group, no login shell and no supplementary groups. The account has no template-storage role. Its sysusers entry is created explicitly after the install gate succeeds; automatic RPM user/group creation is filtered so a rejected install does not create it first.

The USB rule matches VID/PID/revision, removes desktop-user `uaccess`, and grants mode 0660 to the dedicated group. A package-owned SELinux module at priority 200 permits the daemon-domain capability checks needed to drop UID/groups and terminate the unprivileged child: setuid, setgid and kill. A separate yamila_engine_memfd_t type labels tmpfs files created by this domain (not just a filename-matched individual memfd) and permits their bounded read/write/execute mappings. Generic tmpfs_t files receive no new write or execute grant. Other SELinux checks remain active. The service sets a hard core-dump limit of zero; the guard inherits it and avoids a redundant setrlimit call. Opening the device also initializes and discards an in-memory vendor enrollment without images, so runtime failures are reported before requesting a finger. The runtime uses the fixed libusb ELF SONAME and does not launch ldconfig/compiler helpers. Unknown module priorities and administrator-modified module sources are refused on upgrade/removal. No PAM/authselect configuration is changed. Templates are managed by native fprintd; RAW FpPrint is not encrypted by this driver. Existing encrypted stores are not imported or removed.

## Build

Run as an ordinary user with bubblewrap and the exact development packages in `fedora44-build.lock.json`. The source RPM includes the complete pinned libfprint archive and the audited project source, including vendor identity/notices and the DLL.

```sh
python3 -B tools/audit.py
python3 -B tools/rpm.py --upstream-archive /path/to/libfprint-v1.94.100.tar.gz \
    --workdir build/rpm
python3 -B tools/inspect_rpm.py build/rpm/RPMS/x86_64/yamila-libfprint-0.0.1-10.fc44.x86_64.rpm
```

The builder uses bubblewrap to expose its writable work directory at a fixed build path and keeps host inputs read-only. This is a mount sandbox over the host, not a clean Fedora image. RPM 6 embeds expanded spec paths in the source-RPM header, so the fixed path is needed even when ELF payloads already match. The build also fixes `SOURCE_DATE_EPOCH`, build-host metadata, source tar ownership/order/timestamps and source-path maps. Native workers honor the Fedora compiler/linker flags. Staging uses Meson's install copy to remove build-only RUNPATH before RPM processing. The private library does not provide the global `libfprint-2.so.2` RPM capability.

For development on a host without registered development RPMs, the builder has explicit `--local-headers` and `--allow-missing-build-deps` options. This sets rpmbuild's dependency-check override and records it in `build-record.json`; **it is not a clean-environment build**. Runtime RPM dependencies remain declared and checked. This override is never an installation flag.

## Preflight and activation

Read-only inspection, with no service activation, USB access or biometric reads:

```sh
python3 -I -B packaging/preflight.py
```

The package embeds the same gate in its pre-install script. It refuses unsupported versions, full/custom/masked fprintd units, unknown drop-ins, local Yamila USB rules, unknown private-runtime files, modified installed package files and incompatible account/group definitions. It does not remove another gateway, overwrite unknown administrator configuration or migrate templates. Modified managed integration files are also protected by RPM's config preservation rules.

If another Yamila gateway is installed, keep its recovery package and matching maintenance tool before any migration. Use that distribution's documented uninstall/restore process and check its result first. Never force this package over the other gateway or use `--nodeps` to bypass runtime checks. On an existing working setup, migration requires a separate acceptance window and a concrete restore plan.

For a separately prepared, compatible test system, verify the RPM checksum and review `tools/inspect_rpm.py` output before running the finite administrative transaction:

```sh
pkexec /usr/bin/dnf install /absolute/path/yamila-libfprint-0.0.1-10.fc44.x86_64.rpm
```

These development artifacts are unsigned; a checksum is not a signing identity. Release downloads include SHA256SUMS; a signed package repository is not currently provided. Installing adds the account/rule/drop-in, reloads relevant configuration, applies the rule to the exact USB target and restarts fprintd only if it is already running. Installing this preview does not prove fingerprint login or password fallback.

## Upgrade, rollback and removal

Retain the previous RPM and checksum. The same pre-install gate runs for upgrades and downgrades. A failed pre-install gate leaves the old payload selected; RPM transactions are not claimed to be atomic across arbitrary disk/power failures.

```sh
pkexec /usr/bin/dnf upgrade /absolute/path/new-yamila-libfprint.rpm
pkexec /usr/bin/dnf downgrade /absolute/path/previous-yamila-libfprint.rpm
pkexec /usr/bin/dnf remove yamila-libfprint
```

Uninstall stops native fprintd, removes only package-owned integration/runtime, reloads configuration and returns subsequent native-daemon activation to the distribution library. Modified integration files may be saved with `.rpmsave`. The dedicated account, fprintd template data and any previous encrypted data are retained. The package does not delete users, templates, keys or other distributions' recovery assets. To restore a previous custom gateway, first remove this RPM, then use that gateway's own retained installer and recovery guide; do not combine both active integrations.

For read-only package integrity inspection use `rpm -V yamila-libfprint`. After a supported package-baseline update the community package and its lock need a deliberate rebuild/validation; there is no automatic ABI compatibility promise.

## Isolated checks

`packaging/tests/test_preflight.py` uses synthetic filesystem/RPM facts. `packaging/tests/rpm_lab.py` runs actual package scriptlets and install/upgrade/downgrade/remove operations in a user/mount/PID namespace, using seeded host RPM metadata and a minimal runtime. It exposes no real system bus or USB devices. Distribution file triggers, real service activation and SELinux are not validated by that lab. Independent userspace build roots can be assembled from verified Fedora RPM payloads with a fresh RPM database; their skipped bootstrap scripts and generated links must be recorded. This validates normal BuildRequires independently of the host, while booted clean-system installation remains not fully validated and native-service hardware results are separately scoped in the support matrix.
