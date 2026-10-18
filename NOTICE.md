# Source and binary notices

The community driver, broker, protocol implementation, worker IPC, ABI layout declarations and tooling are provided under LGPL-2.1-or-later. See `LICENSES/LGPL-2.1-or-later.txt`. File-level origins and licenses are recorded in `public-files.json` and the checksum-bearing `PUBLIC-MANIFEST.json`.

`native/native_loader.c` derives from `src/ft_engine.c` in [OMGrant/ft9201-libfprint](https://github.com/OMGrant/ft9201-libfprint/tree/fcf5499c6ddadf0d2a03be14b173609e760a7ec6), commit `fcf5499c6ddadf0d2a03be14b173609e760a7ec6`, licensed LGPL-2.1-or-later by that project. The original loader attribution is retained. Local changes pin the Yamila DLL, reject unsupported Windows APIs, add audit counters, use the Yamila WinBio layout and map code/data with separate RX/RW protections. The other device's USB protocol and enrollment/matching wrappers are not used. The ABI declarations describe the WinBio interface layout; they do not bundle Windows SDK headers.

The libfprint dependency is independently versioned and downloaded as the unmodified, checksum-pinned upstream source archive described in `upstream.lock.json`. Its upstream licenses and notices, including the NBIS/NIST public-domain material, remain in that source archive. The integration script adds the Yamila driver and fixes the pinned version's introspection-disabled Meson test branch; it does not claim ownership of upstream source. Source distributions of a combined libfprint binary must retain the corresponding complete upstream source and these modifications.

`vendor/YmlWbioEngineAdapter.dll` is a separate proprietary Yamila binary. Its fixed identity, origin and independent notice are in `vendor/source.json` and `vendor/LICENSE-NOTICE.md`. It is bundled with this source tree and intended distribution assets, is not relicensed under LGPL, and is not covered by the source-code license. No independent vendor redistribution grant has been verified.

GUsb, libusb, GLib/GIO, OpenSSL and the system C runtime are external build/runtime dependencies; their source and binaries are not copied into the public source tree. No Wine runtime is used.
