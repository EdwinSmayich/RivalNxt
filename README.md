<div align="center">

<img src="./src-tauri/icons/frontendlogo.ico" alt="RivalNxt Logo" width="128" height="128">

# RivalNxt — Community Fork

### Marvel Rivals Mod Manager

A desktop app to install, organise and switch Marvel Rivals mods, with conflict
detection, Nexus Mods integration and a local database.

[![Windows](https://img.shields.io/badge/platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white)](#installation)
[![Version](https://img.shields.io/badge/version-1.0.6-success?style=for-the-badge)](#)
[![Tests](https://img.shields.io/badge/tests-1%2C450%20passing-brightgreen?style=for-the-badge)](#verification)

</div>

---

## Credit where it belongs

This is a **fork of [Rounak77382/RivalNxt](https://github.com/Rounak77382/RivalNxt)**.
The application, its architecture and the hard parts — reading Unreal `.pak`
containers, the Rust UE Tools library, asset extraction, the conflict engine,
Nexus ingestion — are **Rounak77382's work**, and most of that code is untouched
here.

Measured against upstream's current `main`, which has moved on since this fork
was taken:

| | |
|---|---|
| Files in the upstream tree | 344 |
| Modified | 62 |
| Deleted | 45 |
| Moved | 20 |
| **Left exactly as the author wrote them** | **217 (63%)** |
| Files this fork adds | 105 |
| Diff | +32,423 / −14,209 across 232 files |

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
- **A rebuild ungrouped mods it could not re-identify.** The upsert wrote the
  scanned `mod_id` unconditionally, so a scan that read no id put `NULL` over a
  good one — and both grouping and artwork are keyed on it, so an `Addons`
  download detached from its base mod and lost its images, every rebuild.
  It read no id because both filename patterns anchor on a Unix epoch, and
  Nexus also writes `..._9902_1_2026-06-20T19-12Z_V1FxDq0Zh.rar`. 12 of 209
  downloads in one library; 8 of them `_Addons_` files.
- **Every hero was renamed `Character 1015`.** Character names are read from the
  game's `.locres` files, and the extractor built its scratch directory from a
  *relative* path — so it landed wherever the process happened to be running,
  and the backend is spawned with no working directory of its own. From an
  unwritable one it returns no names at all, and the combine step then names
  every character after its id. `INSERT OR REPLACE` made that permanent: one
  failed rebuild overwrote all 80 real names, and every rebuild after wrote the
  same placeholders again. Skin names have the same fallback and are guarded
  the same way; they survived only because they have a wiki fallback that
  character names do not.
- **Downloads cut short were kept as finished archives.**
  `HTTPResponse.read(n)` does not raise when the server hangs up early; it
  returns `b""`, and the transfer loop took that for the end of the file. Six
  archives in one library were truncated that way, which surfaced only on
  activation, as `Failed the read enough data: req=1048576 got=1018368`.
  Transfers now go to a `.part` file, are checked against the announced length
  and for an archive signature, and only then renamed. Files added by hand and
  images added by address had the same hole and are closed the same way.
- **One file downloaded six times over, and Cancel did nothing.** Every arrival
  of a download link started its own transfer, and every pending transfer
  started at once — past the webview's six connections per host, so the
  progress polls and the Cancel request queued behind the downloads
  themselves. A repeated link now joins the transfer already running, two run
  at a time, and what is waiting can be cancelled.
- **A mod could be left made of two versions.** A mod is three files — `.pak`,
  `.utoc`, `.ucas` — that only work together, and the game keeps the `.ucas`
  open while it runs. Installing replaced them one at a time, deleting each
  working file first, so a damaged archive or a running game left a new `.pak`
  beside an old or half-written `.ucas`. The set now goes in together or not at
  all, and when the game has a file open the app says so — "close the game and
  try again" — instead of half-finishing. Switching off, sorting into folders
  and deleting a download follow the same rule; each used to swallow the
  failure, which is how `.ucas` files with nothing left to load them piled up.
- **"Disable all" deleted mods it could not restore.** The crash dialog's
  button removed every file under `~mods`, including mods the app did not
  install and so had no archive for. Those are now moved to a
  `RivalNxt disabled mods` folder beside the game, and the dialog says where.
- **`settings.json` could come back empty** — the file holding the Nexus key
  and both folders. It was written in place, so a reader in another thread
  could catch it empty (59 times in 150 saves, measured), fall back to the
  defaults, and have the next save write those to disk. It is now replaced in
  one step, with the previous version kept as `settings.json.bak`.
- **Mods lost their name and picture when Nexus hid them.** The sync wrote a
  mod's whole row from each answer, so a 403, a rate limit, no network, or a
  mod under moderation replaced everything with `NULL` — 33 of 200 mods in one
  library. A failed answer now changes nothing, and a migration recovers the
  names from the refusals Nexus sent: 29 of the 33. Pictures cannot be had back
  that way.
- **A number in a mod's name was taken for its Nexus id.**
  `the-ting-v1-1-6853-1.1-1771860521.zip` was filed under mod 1. The id is now
  located from the timestamp and version at the end of the name: on one
  library's 283 file names, 260 parse as before, 4 get the right id and 19 lose
  a version that had half the file name in it. Rows already misfiled are
  corrected at start-up.
- **Every dialog closed without its fade, and logged a warning doing it.**
  The dialog components were written for React 19, which hands a component
  its ref as an ordinary prop; on React 18, which the app runs, the overlay
  needs `forwardRef`, or Radix cannot follow its closing animation.

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
- **Game patch awareness** — a patch can stop every mod applying at once. The
  date is read off the game's own containers, and mods whose author has posted
  anything since are listed, so you are not opening 167 cards to find out who
  has rebuilt. Labelled "updated since the patch", not "fixed": an author may
  have changed a screenshot.
- **Voice subtitles** — see below

### Voice subtitles

A voice mod changes what a hero says, but the subtitle on screen is still the
game's line. The **Voice Subtitles** tab listens to each voice mod — the ones
switched on and the ones only in your library — and writes subtitles for what
it actually says: in English as heard, or translated into any language the game
ships. Everything runs on your computer; nothing is sent anywhere.

Nothing is installed until you ask for it:

| Step | Download | Needed for |
|---|---|---|
| Speech recognition (Whisper large-v3-turbo, whisper.cpp, vgmstream) | 0.9 GB | any subtitles |
| …on an NVIDIA card instead of the processor | +0.7 GB | optional |
| A translation model (Gemma 4, llama.cpp) | 8–19 GB | subtitles in a language other than English |

The tab reads your graphics card and memory, says which models fit, and
recommends one:

| Model | Download | Made for | Seconds a line, measured |
|---|---|---|---|
| Gemma 4 31B, 4-bit | 19 GB | NVIDIA cards with 24 GB | — |
| Gemma 4 31B, 3-bit | 14 GB | NVIDIA cards with 16 GB | 2.1 |
| Gemma 4 26B-A4B | 15 GB | 8–12 GB cards, or a processor with 32 GB of memory | 5.4 (12 GB card), 8.6 (8 GB), 1.3 (processor) |
| Gemma 4 12B | 8 GB | 8 GB cards, or 16 GB of memory | 1.6 (processor) |

Measured on one PC — a 16 GB RTX 5080 and a 16-core processor — with the
smaller cards simulated by leaving memory unused; a voice mod changes from a
few dozen lines to a few hundred. On a graphics card each line is reasoned over before it is written; on
the processor alone it is not, which is quicker and slightly less careful. In
Russian, the language tested, the 31B models read the most naturally, the
26B-A4B is close behind, and the 12B is correct but more literal.

Every download is a pinned version, checked against its SHA-256 before use, and
resumes where it stopped.

Each voice mod gets **its own subtitle mod** in your library — an ordinary
archive named `RU Subtitles - <hero> - <voice mod>.zip`, filed under its hero
and switched on and off like any other mod, so two variants of one voice can
have their own subtitles and only the one you use is on. The game reads one
text file per language, so the lines of every subtitle mod that is on are
written into a single `zzz_RivalNxt_Subtitles_9999999_P.pak`, rebuilt a few
seconds after mods change and removed when none is on. English subtitle mods
show in a game set to any language; where a voice mod has subtitles in two
languages switched on, the game's language wins.

- **Review and correct** any line; the subtitle mod is rewritten at once, and
  corrections are shown to the translator as examples for later lines
- **A line the mod silences** gets no subtitle; a line it leaves alone keeps
  the game's
- **Stopping is safe** — cancelled, the app closed, or the game started: the
  work so far is kept and the next run continues from there. While Marvel
  Rivals is running, the work waits, so the game keeps the graphics card
- **Content limits.** Voice mods for Peni Parker, a teenager, and Jeff the Land
  Shark, an animal, get no subtitles. A sexual line in any other voice mod
  keeps the game's own subtitle when it names or answers one of them, or names
  a real animal

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

1. Download `RivalNxt_1.0.6_x64-setup.exe` from
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
npm run typecheck && npm test        # 294 frontend tests
python -m pytest tests/backend -q    # 1,156 backend tests
ruff check core scripts src-python
```

Seventeen further tests check that the shipped bundle is actually code-split.
They read `dist/`, so they skip unless you have run `npm run build` first —
deliberately, because a test that cannot see its subject should say so rather
than pass. With a build present the total is 1,467.

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
- **[whisper.cpp](https://github.com/ggml-org/whisper.cpp)**,
  **[llama.cpp](https://github.com/ggml-org/llama.cpp)**,
  **[vgmstream](https://github.com/vgmstream/vgmstream)**, OpenAI's Whisper and
  Google's Gemma (as quantised by [Unsloth](https://huggingface.co/unsloth)) —
  voice subtitles. None of them is bundled: each is downloaded from its own
  project when you ask for it, under its own licence
