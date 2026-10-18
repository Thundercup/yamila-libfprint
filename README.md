# Yamila fingerprint driver for Linux

[简体中文](README.zh-CN.md) · [Releases](https://github.com/Thundercup/yamila-libfprint/releases) · [Support matrix](docs/SUPPORT.md)

[![Synthetic checks](https://github.com/Thundercup/yamila-libfprint/actions/workflows/synthetic.yml/badge.svg)](https://github.com/Thundercup/yamila-libfprint/actions/workflows/synthetic.yml)
[![Packages](https://github.com/Thundercup/yamila-libfprint/actions/workflows/packages.yml/badge.svg)](https://github.com/Thundercup/yamila-libfprint/actions/workflows/packages.yml)

An experimental community driver for **Yamila USB fingerprint readers with VID:PID `2808:06fc` and revision `0x2003`**. It connects the distribution's native **fprintd** to a private libfprint backend and an isolated algorithm worker.

- Supports fingerprint enrollment and one-to-one verification through standard fprintd clients.
- Includes the fixed vendor algorithm binary; no Windows extraction or Wine installation is required.
- Keeps the distribution libfprint installed and loads the patched library only for fprintd.
- Runs the vendor algorithm under a dedicated account, outside the privileged daemon.

This is a **community preview**, not a production support guarantee. Other readers, revisions, ARM platforms, identify, cross-finger duplicate detection and boot-login acceptance are outside the current scope.

## Supported packages

| System | Architecture | Package | Authentication integration |
| --- | --- | --- | --- |
| Ubuntu 26.04 | amd64 | DEB | Automatically enables the distribution fingerprint PAM profile on first configuration; preserves password authentication and administrator choices |
| Fedora 44 | x86_64 | RPM / SRPM | Private library and package-owned SELinux policy; existing PAM/authselect configuration is retained |

Packages enforce a specific distribution baseline. The Fedora build requires libfprint `1.94.100-1.fc44`, fprintd `1.94.5-5.fc44` and targeted SELinux policy `44.11-1.fc44`. Each Ubuntu build records its exact native package versions and service-unit digest in `build-record.json`. Unsupported baselines and conflicting configurations are refused; do not bypass dependency checks.

Limited hardware validation includes Fedora enrollment, persistence, match/rejection, cancellation, sudo/password fallback and reported KDE management/lockscreen/administrator authentication. Ubuntu reports cover GNOME setup/lockscreen and sudo, Polkit and password fallback after enabling the distribution PAM profile. Automatic DEB setup/removal has container transaction coverage; integrated installation of the new public package on hardware is not yet accepted. See [the detailed matrix](docs/SUPPORT.md).

## Install

Download the appropriate package and `SHA256SUMS` from [Releases](https://github.com/Thundercup/yamila-libfprint/releases). Verify the checksum before installation. Packages are currently unsigned; checksums detect corruption but do not establish a package signer. Retain your password and a recovery path for any previous driver.

### Ubuntu 26.04

```sh
sudo apt install ./yamila-libfprint_0.0.1-3ubuntu26.04_amd64.deb
sudo dpkg --verify yamila-libfprint
```

On a standard managed PAM configuration, no separate enable command is needed. The installer uses `pam-auth-update`, keeps Unix password authentication and other profiles, and never forces local PAM edits. A conflict can leave package configuration incomplete and must be reviewed explicitly. To opt out afterward:

```sh
sudo pam-auth-update --disable fprintd
```

See [Ubuntu installation, rollback and removal](docs/UBUNTU.md).

### Fedora 44

```sh
sudo dnf install ./yamila-libfprint-0.0.1-10.fc44.x86_64.rpm
rpm -V yamila-libfprint
```

The package manages its SELinux module and exact USB rule. It does not edit PAM/authselect. Read the [Fedora installation and recovery guide](packaging/INSTALL.md), including the exact baseline and conflict checks, before migrating an existing driver.

## Enroll and verify

Once installation and device discovery succeed, use GNOME/KDE settings or the standard clients:

```sh
fprintd-list "$USER"
fprintd-enroll -f right-index-finger "$USER"
fprintd-verify -f right-index-finger "$USER"
```

Enrollment and verification request a touch immediately. Existing encrypted templates from another driver are not converted; enroll a new native template when ready. Native RAW FpPrint records have no additional driver-level encryption and rely on protected system storage. Keep password authentication available.

## Build and test

Install the development dependencies described in the [Fedora](packaging/INSTALL.md#build) or [Ubuntu](docs/UBUNTU.md#build) guide, then build as an ordinary user:

```sh
python3 -B tools/audit.py
python3 -B tools/release_check.py
python3 -B tools/build.py --fetch-upstream --test-mode
python3 -B tools/check.py
```

[Upstream libfprint](upstream.lock.json) is pinned by version and SHA-256. Default tests use synthetic data; test builds cannot be installed. CI runs synthetic checks and builds Fedora RPM/SRPM and Ubuntu DEB packages without USB access or executing the vendor DLL. Package artifacts include corresponding sources, build records and checksums.

## License and vendor component

Project-authored source is **LGPL-2.1-or-later**. The bundled `YmlWbioEngineAdapter.dll` remains a **proprietary Windows x64 binary**, executed by a Linux compatibility worker. It is not open-source algorithm code or covered by the project license. See [source notices](NOTICE.md), [the LGPL text](LICENSES/LGPL-2.1-or-later.txt) and [the vendor notice](vendor/LICENSE-NOTICE.md).

## Help and contributions

- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Support and known limitations](docs/SUPPORT.md)
- [Contributing](CONTRIBUTING.md)
- [Change log](CHANGELOG.md)

Report the relevant system/package versions and a minimal error description. Do not attach fingerprint images, templates, keys, passwords or raw USB captures to issues.
