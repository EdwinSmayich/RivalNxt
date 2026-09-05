<div align="center">

<img src="./src-tauri/icons/frontendlogo.ico" alt="RivalNxt Logo" width="128" height="128">

# RivalNxt — Community Fork

### Marvel Rivals Mod Manager

A desktop app to install, organise and switch Marvel Rivals mods, with conflict
detection, Nexus Mods integration and a local database.

[![Windows](https://img.shields.io/badge/platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white)](#installation)
[![Version](https://img.shields.io/badge/version-1.0.1-success?style=for-the-badge)](#)
[![Tests](https://img.shields.io/badge/tests-880%20passing-brightgreen?style=for-the-badge)](#verification)

</div>

---

## Credit where it belongs

This is a **fork of [Rounak77382/RivalNxt](https://github.com/Rounak77382/RivalNxt)**.
The application, its architecture and the hard parts — reading Unreal `.pak`
containers, the Rust UE Tools library, asset extraction, the conflict engine,
Nexus ingestion — are **Rounak77382's work**, and most of that code is untouched
here.

Measured against upstream at the time of this fork:

| | |
|---|---|
| Files in the upstream tree | 338 |
| Modified | 44 |
| Deleted | 39 |
| Moved | 20 |
| **Left exactly as the author wrote them** | **235 (70%)** |
| Files this fork adds | 48 |
| Diff | +17,910 / −12,944 across 151 files |

This fork fixes bugs and adds features on top of that foundation. It is not a
rewrite, and it would not exist without the original. Check the numbers rather
than take them:

```bash
git remote add upstream https://github.com/Rounak77382/RivalNxt.git && git fetch upstream main && git diff --stat -M upstream/main..HEAD
```

---

## Why this fork exists

A single session of real use surfaced a set of faults, each traced to a root
cause rather than patched at the symptom.

### Backups did not work

**Creating one failed outright** on any sizeable library. The export serialised
every custom image as base64 into one JSON string; a library with a few hundred
mods produced a string past V8's maximum length and `JSON.stringify` threw
`Invalid string length`. No file was written. Backups now snapshot the database
itself through SQLite's online backup API, so nothing is serialised in the
webview at all.

**Restoring one crashed** with `OSError: [Errno 22] Invalid argument`. SQLite
keeps `mods.db` memory-mapped (`PRAGMA mmap_size = 256MB`), and Windows refuses
to truncate a file with a live mapped section — a condition CPython has no errno
for, so it surfaced as that unhelpful message. The restore now writes *through*
SQLite instead of replacing the file behind its back.

**Restoring still changed nothing visible**, because a mod is active when its
`.pak` sits in the game's `~mods` folder, not when a column says so. Restoring
rewrote the column and moved no files — and the next refresh pruned the column
back to match the disk. The restore now puts the files back too.

### Other fixes

- **"Rebuild Local Downloads" appeared to hang** at `2/213` forever. The task had
  finished in 5.76 s; the progress parser treated "processed < total" as
  in-flight, and skipping unchanged archives made that permanently true.
- **Removed files came back** after every rebuild. The removal edited
  `local_downloads.contents`, which the ingest rewrites from the archive.
  Removals are now recorded separately and applied when the mod is read.
- **Images vanished when a mod was linked** to Nexus. Anything attached to an
  unlinked download is keyed by the negated download id; linking changed which
  key the app reads without moving the rows. They are carried across now, and
  two migrations recover the ones already stranded.
- **Manual Mod IDs were lost** on every "Initial Database Build": the id is
  parsed from the file name, which no longer contains one after the app renames
  a file, and the override table nobody read held the answer.
- **452 of 646 CSS classes did nothing.** `src/index.css` was a snapshot of
  Tailwind's output, so any class added after that snapshot had no rule —
  missing padding, margins and icon sizes across the whole app. A real Tailwind
  build now generates them from source.
- **Mods piled up loose at the root of `~mods`** instead of going into their
  character folder. `active_paks` stores the path a pak has *inside its archive*
  — `LunaSnow_AbyssalGlow_Symbiote/LunaSnow_AbyssalGlow_Symbiote_9999999_P.pak`
  — and the tag lookup is keyed by the bare filename, so every mod whose archive
  nests its paks in a folder found no tags, resolved to no character, and was
  filed at the root. 73 of 115 active downloads in one library. The fallback,
  matching hero names against the download name, cannot help when the mod is not
  named after its hero: `The Ting` is a The Thing skin and `makeup file` is a
  Luna Snow one. Deleting a mod's tag and adding it again was the only
  workaround, because custom tags are read before that lookup.
- **"Sort Mods Into Folders" rewrote the library from its archives.** It
  re-activated every active download, and activation re-extracts each
  destination whether or not it is already correct — so sorting three strays
  re-extracted everything, and a mod whose archive had moved could never be
  sorted at all. It now moves the files.

### Added

- **Restore points** — full snapshots and mod loadouts in one list, newest
  first, with what each covers stated on the row
- **Named presets** for switching between sets of mods
- **Bulk operations** — select many mods, then enable, disable, tag or delete,
  with a single conflict rebuild for the batch rather than one per mod
- **History** — what the app changed and when, so "did that apply?" has an answer
- **Per-file notes and hiding** — mods ship a dozen variants named `A_rogueVA`,
  `A_rogueVB`…; write down which is which, hide the ones you do not want, or
  delete them from the archive outright
- **Images from the mod's own archive** — 45% of archives ship screenshots next
  to the `.pak` files; pick them from a grid instead of hunting for links
- **Nexus browsing** by name, with adult-content and category filters
- **Progress with a percentage and an estimate**, instead of a count that stalls

### Measured improvements

| | Before | After |
|---|---|---|
| Asset ingest | 252.3 s | 57.7 s (4.4×) |
| Repeat ingest | full re-extract | 6.0 s (fingerprint skip) |
| Database size | 2.2 GB | 126 MB |
| Duplicate images | 1,050 of 1,352 rows | 0 |
| Nexus sync on rebuild | ~390 requests | skipped when fresh |

The last one matters on a free Nexus key, which allows 100 requests an hour: a
single rebuild used to exhaust the budget and start failing partway.

---

## Installation

1. Download `RivalNxt_1.0.1_x64-setup.exe` from
   [Releases](../../releases/latest)
2. Run it. Windows SmartScreen will warn about an unsigned installer — the build
   is not code-signed; choose **More info → Run anyway**, or build from source.
3. On first launch, set your Marvel Rivals folder and your mod downloads folder
4. Optionally add a Nexus API key in Settings to enable metadata and update checks

Your Nexus API key is stored in `%APPDATA%\com.rivalnxt.modmanager\settings.json`
and never leaves your machine.

---

## Building from source

```bash
git clone --recurse-submodules https://github.com/EdwinSmayich/RivalNxt.git
cd RivalNxt
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
build_local.bat
```

Requires Node 20+, Python 3.11, Rust, and WinRAR or 7-Zip for `.rar`/`.7z`
archives. The script installs npm dependencies, builds the Rust PyO3 module with
maturin, bundles the Python backend with PyInstaller, and produces the installer.

The `.venv` is not optional: the build uses that interpreter explicitly rather
than whatever `python` resolves to, and puts `.venv\Scripts` and cargo on `PATH`
itself. 1.0.0 was built by an interpreter that happened not to have Pillow, and
shipped a backend that could not resize an image — silently, because PyInstaller
reports a missing module as a warning and exits 0. The build now checks the
bundle before calling itself done.

### Verification

```bash
npm run typecheck && npm test        # 238 frontend tests
python -m pytest tests/backend -q    # 642 backend tests
ruff check core scripts src-python
```

Seventeen further tests check that the shipped bundle is actually code-split.
They read `dist/`, so they skip unless you have run `npm run build` first —
deliberately, because a test that cannot see its subject should say so rather
than pass. With a build present the total is 897.

---

## Licence

**The upstream project carries no licence**, which means all rights are reserved
by its author. This fork exists under the licence GitHub grants for public
repositories ([GitHub ToS §D.5](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#5-license-grant-to-other-users)),
which permits viewing and forking — nothing more.

If you want to reuse this code beyond that, ask
[Rounak77382](https://github.com/Rounak77382/RivalNxt) first. The upstream README
asks exactly this, and it is a reasonable request.

The bundled Oodle libraries (`oo2core_9_win64.dll`, `liboo2corelinux64.so.9`) are
proprietary and are not covered by any of the above.

---

## Contributing back

Fixes here are offered upstream rather than kept. If you are the original author
and want any of this, take it — no attribution needed, no PR ceremony required.

## Acknowledgements

- **[Rounak77382](https://github.com/Rounak77382)** — the application itself
- **[repak](https://github.com/trumank/repak)** — Unreal `.pak` handling
- **Nexus Mods** — the API this integrates with
