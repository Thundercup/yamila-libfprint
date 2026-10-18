# Ubuntu 26.04 experimental amd64 package

This target is for **Ubuntu 26.04 amd64, USB 2808:06fc revision 0x2003**. The DEB has been built and inspected in a rootless Ubuntu container. A user reported working GNOME fingerprint configuration and lockscreen unlock with revision 1. Revision 2 adds automatic PAM setup; sudo/Polkit fingerprint authentication and password fallback were subsequently reported working after manual activation of the same distro profile. Automatic installation of the new public package on hardware remains unaccepted. Full booted-system lifecycle and AppArmor integration remain unaccepted. Do not transfer Fedora hardware results to Ubuntu. Other Ubuntu releases and Debian-family derivatives are welcome for community testing, without a compatibility claim. The included vendor engine requires x86_64; ARM is not supported.

## Build

In an Ubuntu 26.04 build environment, install build prerequisites:

```sh
sudo apt-get update
sudo apt-get install build-essential meson ninja-build pkg-config python3 libglib2.0-dev libgusb-dev libusb-1.0-0-dev libjson-glib-dev libssl-dev dpkg-dev binutils fprintd libfprint-2-2 libpam-fprintd systemd udev ca-certificates
```

Then build as an ordinary user from this audited source:

```sh
python3 -B tools/audit.py
python3 -B tools/privacy_check.py
python3 -B tools/fetch_upstream.py --dest /tmp/libfprint-upstream.tar.gz
python3 -B tools/deb.py --upstream-archive /tmp/libfprint-upstream.tar.gz --workdir /tmp/new-yamila-deb
python3 -B tools/inspect_deb.py /tmp/new-yamila-deb/yamila-libfprint_0.0.1-4ubuntu26.04_amd64.deb
```

The work directory must be new. Retain the DEB, project source archive, full pinned upstream source archive and build-record.json together. The overlay plus upstream archive is the corresponding source; the proprietary DLL remains subject to its separate notice. The recorded baseline contains exact installed libfprint/fprintd versions and the native service unit digest for build provenance, not an exact-version installation requirement. Runtime package dependencies are unpinned; generated ELF dependencies still apply. Older systems may need a source build if their libraries cannot satisfy the downloadable binary. Currently observed: libfprint-2-2 `1:1.95.1+tod1-0ubuntu2`, fprintd `1.94.5-4`. A package rebuilt after distribution updates may record a different baseline; that is a new experimental build, not new hardware validation.

## Before installation

Review the build record and package inspection. With required distribution dependencies installed, this optional read-only check previews the installation gate:

```sh
sudo python3 -I -B packaging/debian/preflight.py --baseline /tmp/new-yamila-deb/package/usr/share/yamila-libfprint/baseline.json
```

Use the real source/build paths. OS/package version differences and changes to the distribution service-unit digest only produce compatibility warnings. The gate still refuses a different CPU architecture, missing required packages/native service unit, custom service overrides, local Yamila USB rules, unknown private runtime files, modified installed package files or an incompatible worker account. It also refuses a visible enforced fprintd AppArmor profile and enforcing SELinux: Ubuntu-specific policy integration is unimplemented. Do not disable confinement or bypass the gate to install.

The private library uses `/usr/lib/x86_64-linux-gnu/yamila-fprint`; runtime code uses `/usr/libexec/yamila-fprint`. Only the native fprintd receives this library path. The distribution library remains installed; this preview library registers only the Yamila reader. A sysusers account and a rule for the exact USB identity grant access to the isolated worker. MDWE/NNP stay enabled; the drop-in sets core limit 0. Revision 2 depends on the distribution libpam-fprintd and enables its existing fprintd PAM profile on first configuration through pam-auth-update. It keeps the existing Unix password and other profiles. This applies to all services that include common-auth, including typical sudo/Polkit paths; it does not guarantee every application uses that stack. Existing native templates remain; old encrypted templates are not converted. Keep your password and previous recovery files.

## Automatic fingerprint authentication

Installing or upgrading to revision 2 or later automatically enables the distribution fingerprint profile if it is currently off and a managed Unix password fallback exists. No extra enable command is needed on a standard supported installation. The tool runs noninteractively and never uses --force or manually writes PAM jump counts. If local edits prevent the distro tool from applying the profile, package configuration fails with a clear error; resolve the local policy explicitly rather than forcing it.

A root-only receipt in `/var/lib/yamila-libfprint/pam-state.json` records prior preference and configuration hashes, without passwords or biometric data. Reconfiguration/upgrade respects subsequent administrator choices. Preexisting fingerprint enablement is kept. On removal, only a profile enabled by this package with unchanged configuration is disabled again. Administrator changes cause removal to retain the current preference and print a notice. Other PAM profiles, worker accounts and template stores are preserved. Downgrading to revision 1 attempts the same conditional PAM rollback; a harmless receipt can remain until a later revision 2 configuration/removal.

For an explicit administrator opt-out after installation:

```sh
sudo pam-auth-update --disable fprintd
```

This preference survives reconfiguration. To enable it again explicitly, use `sudo pam-auth-update --enable fprintd`. PAM is sequential: fingerprint authentication can wait up to the distro profile timeout before falling back to a password. Keep password authentication enabled and verify that fallback on the actual computer.

## Install and remove on the test computer

Installation enables fingerprint authentication in managed common-auth, may restart an already active fprintd and changes access to this reader. Do it outside any active authentication session:

```sh
sudo apt install ./yamila-libfprint_0.0.1-4ubuntu26.04_amd64.deb
sudo dpkg --verify yamila-libfprint
```

The expected verification output is empty. The package now performs PAM setup, so inspect the resulting common-auth and confirm the existing password modules are retained. Before touch testing, inspect `systemctl cat fprintd.service` and `systemctl status fprintd.service`; hardware enrollment and verification are a separate, coordinated test. A container build/install does not prove that the daemon can open hardware or execute the vendor algorithm under Ubuntu confinement.

To return to the distribution backend:

```sh
sudo apt remove yamila-libfprint
```

Removal first performs the conditional PAM preference rollback described above, then stops an active fprintd and reloads unit/USB rules. Later D-Bus activation uses the distribution backend again. This reader will lack the community backend after removal. The package keeps the worker account and fingerprint stores. Its three integration files live in `/usr` as regular package files, not retained conffiles, so removal removes its drop-in. Installation/upgrade/removal verify package content and refuse modified files; review modifications explicitly rather than forcing transactions. Package checks do not independently prove a booted system's lifecycle or rollback.
