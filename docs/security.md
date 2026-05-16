# Security & SmartScreen — the long version

## Why Windows warns you about `gui.exe`

Microsoft SmartScreen flags any Windows executable that:

1. isn't signed with a Microsoft-trusted code-signing certificate, **or**
2. *is* signed, but the signing identity hasn't yet accumulated enough
   downloads / clean-install reports for SmartScreen to consider it
   "established."

This release currently has neither. That doesn't mean the file is
malicious — it means SmartScreen has no opinion about it yet. The
warning is identical to what you'd see for any unsigned freeware,
homebrew tool, or modder utility.

## How to verify it yourself

The Windows zip is built end-to-end by a public GitHub Actions
workflow — `.github/workflows/release.yml` in this repo. Every release
artefact links back to the exact commit and build log that produced
it. You can:

* read the workflow file and confirm there's no out-of-band download
  step beyond the upstream ffmpeg and 7-Zip URLs listed in
  `tools/TOOLS.txt` inside the zip,
* re-run the workflow yourself in your own fork to produce a
  byte-similar zip,
* upload the zip to [VirusTotal](https://www.virustotal.com/) — false
  positives on PyInstaller-frozen Python are common (typically 2–6 of
  the ~70 engines flag any Python EXE that does file I/O), but you can
  see which engines flag and which don't.

## What we do to keep warnings minimal even unsigned

Choices baked into the build that demonstrably reduce false-positive
rates in independent testing:

| Choice | Why |
|---|---|
| One-folder layout, not one-file | One-file bundles extract to `%TEMP%` at startup — a heuristic that AV engines weight heavily |
| No UPX packing (`upx=False`) | UPX is the single strongest "this is malware" signal in most engines' weights |
| Full Windows version resource | Generic-icon unsigned exes with empty Properties → Details are the platonic ideal of suspicious |
| Custom icon, not the PyInstaller default | Same reason |
| GUI is `console=False`, CLI is `console=True` | A windowed exe that *also* spawns a console window is a common backdoor pattern; we don't do that |
| Bundled ffmpeg and 7-Zip are unmodified upstream binaries | We don't re-package them or strip their version resources; AV engines already know these specific builds |

## The actual fix is code signing

Two paths we're considering:

* **[SignPath.io](https://signpath.org/) Foundation OSS programme.**
  Free for qualifying open-source projects. Standard-validation cert,
  which means SmartScreen still needs reputation to build up — but it
  ends "Unknown publisher" immediately.
* **[Azure Trusted Signing](https://learn.microsoft.com/en-us/azure/trusted-signing/).**
  ~$10/month. Microsoft-issued, cleaner integration with GitHub
  Actions, and the cheapest route to a *signed* unsigned-EXE story.
* **EV code-signing certificate.** $300–500/year. The only option that
  gets immediate SmartScreen reputation with zero install history.
  Overkill for a hobby tool but listed for completeness.

The `.github/workflows/release.yml` has a commented-out signing block
already wired for Azure Trusted Signing — flip the comments and add
secrets when a cert is provisioned.

## What this tool actually does at runtime

For paranoid reviewers, here's the full network and filesystem
surface:

* **Network:** binds to `127.0.0.1` only (loopback). No outbound
  network calls anywhere in the codebase. Run `netstat` while it's up
  to confirm.
* **Filesystem reads:** the ISO(s) you point it at, and the `lba/`
  table inside the install dir.
* **Filesystem writes:** only under the working directory you choose
  in the GUI (or `--work` on the CLI). Nothing in your user profile,
  registry, or program-files outside that directory.
* **Subprocesses:** `xeno-cli.exe` (the sibling binary in the same
  folder), `7z.exe`, `ffmpeg.exe`. No `cmd.exe`, no `powershell.exe`,
  no scheduled tasks, no services.

If anything you see contradicts the above, please open an issue.
