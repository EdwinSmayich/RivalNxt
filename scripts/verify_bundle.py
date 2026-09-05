"""Assert the frozen backend actually contains the modules it needs.

PyInstaller reports a module it could not find as a line in warn-*.txt and then
exits 0, so a bundle can come out missing a dependency without failing the
build. That is how 1.0.0 shipped without Pillow: build_local.bat called bare
`python -m PyInstaller`, PATH resolved to an interpreter that did not have it,
and the first sign was "No module named 'PIL'" in a user's log a week later.

PyInstaller writes the contents of the package it built to .toc files next to
the executable's build directory. Reading those is version-independent enough
and does not require running the executable, which would start a server.

Usage: verify_bundle.py dist/rivalnxt_backend.exe
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# Imported from inside functions at runtime, so nothing at build time notices
# their absence and no test covers the frozen bundle.
REQUIRED = ("PIL", "fastapi", "uvicorn", "requests", "rust_ue_tools")


def _collect(node: object, out: set[str]) -> None:
    """Gather the name from every (name, path, typecode) triple in a TOC.

    The files are not flat lists. PKG-00.toc is
    ``(output_path, {flags...}, [entries])`` and Analysis-00.toc nests several
    such lists, so iterating the top level yields a path string, a dict and a
    list rather than entries -- which is how the first version of this reported
    every module missing, including ones plainly in the bundle.
    """
    if isinstance(node, (list, tuple)):
        if len(node) >= 2 and isinstance(node[0], str):
            out.add(node[0])
        for item in node:
            _collect(item, out)
    elif isinstance(node, dict):
        for value in node.values():
            _collect(value, out)


def toc_entries(build_dir: Path) -> set[str]:
    """Every module and binary name PyInstaller recorded for this build."""
    names: set[str] = set()
    for toc in sorted(build_dir.glob("*.toc")):
        try:
            parsed = ast.literal_eval(toc.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError, SyntaxError) as exc:
            print(f"   note: could not parse {toc.name}: {exc}")
            continue
        _collect(parsed, names)
    return names


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: verify_bundle.py <path to built exe>")
        return 2

    exe = Path(sys.argv[1])
    if not exe.is_file():
        print(f"FAIL: {exe} does not exist")
        return 1

    root = Path(__file__).resolve().parents[1]
    candidates = [d for d in (root / "build").glob("*") if d.is_dir()]
    build_dir = next((d for d in candidates if any(d.glob("*.toc"))), None)
    if build_dir is None:
        print(f"FAIL: no PyInstaller .toc files under {root / 'build'};")
        print("      cannot confirm what went into the bundle.")
        return 1

    names = toc_entries(build_dir)
    print(f"read {len(names)} entries from {build_dir.name}")

    missing = []
    for module in REQUIRED:
        present = any(n == module or n.startswith(module + ".") for n in names)
        print(f"   {module:16} {'ok' if present else 'MISSING'}")
        if not present:
            missing.append(module)

    if missing:
        print(f"\nFAIL: the bundle is missing {', '.join(missing)}.")
        print("      Check that the interpreter used for PyInstaller has them:")
        print("      .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1

    print("\nall required modules are in the bundle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
