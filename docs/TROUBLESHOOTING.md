# Troubleshooting

Start with metadata and the exact error, without enrolling again:

```sh
rpm -q yamila-libfprint libfprint fprintd selinux-policy-targeted
rpm -V yamila-libfprint
getenforce
systemctl show fprintd.service -p ExecStart -p Environment -p ActiveState
lsusb -d 2808:06fc
```

These commands do not capture images or read templates. An inactive fprintd can be normal idle shutdown. Only when ready to activate discovery, use `fprintd-list "$USER"`; listing may start the service but does not request a touch.

| Symptom | Next check |
| --- | --- |
| Untested version warning | Testing may proceed if actual dependencies and configuration checks pass. Report the system/package versions and results. |
| Installation refused | Version differences only warn; inspect missing runtime dependencies and conflicting unit/drop-in/USB rules or modified files. Do not force over unknown integration or use --nodeps. |
| Package verification prints differences | Review the changed file; preserve intentional administrator changes before upgrade/removal. Do not blindly replace them. |
| Reader is absent | Confirm VID/PID/revision and the RPM rule/account; other readers are not enabled in this preview. |
| Device open fails before a touch | The driver performs a no-image DLL self-check during open. Check service errors and administrator-reviewed SELinux denials before requesting another finger. |
| Duplicate identification warning | Expected: identify and cross-finger duplicate detection are not implemented. |
| Repeated retry | Retry is not a successful match or an effective negative sample. Stop repetitive collection and report a short status sequence. |
| No templates after changing gateways | Stores are incompatible and are not migrated. Preserve the previous store; enroll a native template only when intentionally switching. |
| Authentication fails | First distinguish standard-client verification from the particular PAM/desktop flow. Keep the password path; do not edit PAM as a generic troubleshooting step. |

If administrator log access is needed, inspect a short time window, for example `journalctl -u fprintd.service --since "10 minutes ago" --no-pager`, and relevant AVC records. Review output locally before sharing a minimal excerpt. A privileged inspection may require your normal system authorization.

Do not share full journals, environment dumps, raw USB captures, images, templates, encryption keys or passwords. Remove usernames, hostnames and unrelated session details from excerpts. An issue needs the version tuple, hardware revision, operation, exact status/error and reproduction steps. See [support limits](SUPPORT.md) and [package removal/recovery](../packaging/INSTALL.md#upgrade-rollback-and-removal).
