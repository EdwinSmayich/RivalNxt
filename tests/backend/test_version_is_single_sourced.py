"""The version must be one number, not six copies of it.

It was written by hand in package.json, tauri.conf.json, core/nexus/graphql.py,
core/nexus/nexus_api.py and twice more as a literal inside a User-Agent header in
core/api/server.py. The headers were the ones that got missed: the app kept
introducing itself to Nexus as a version it had not been for two releases, and
nothing anywhere would have told anyone.

core/version.py is now the Python side of the number and package.json the
JavaScript side. These tests assert they agree and that no literal has crept
back.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _package_version() -> str:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def test_python_matches_package_json():
    from core.version import APP_VERSION

    assert APP_VERSION == _package_version()


def test_the_installer_manifest_matches_too():
    """tauri.conf.json names the .exe, so a mismatch ships a mislabelled build."""
    conf = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    assert conf["version"] == _package_version()


def test_every_module_reports_the_same_version():
    from core.nexus import graphql, nexus_api
    from core.version import APP_VERSION

    assert graphql.APP_VERSION == APP_VERSION
    assert nexus_api.APP_VERSION == APP_VERSION


def test_the_api_advertises_it():
    import core.api.server as server
    from core.version import APP_VERSION

    assert server.app.version == APP_VERSION


def test_the_user_agent_is_built_from_it():
    from core.version import APP_NAME, APP_VERSION, USER_AGENT

    assert USER_AGENT == f"{APP_NAME}/{APP_VERSION}"


# Places an app version is actually assigned. Deliberately not "any x.y.z in the
# file": these modules discuss *mod* version numbers in prose, and a blunt scan
# flagged a comment explaining that "2" matches "2.177.1".
_ASSIGNS_A_VERSION = re.compile(
    r"""(?:
          APP_VERSION\s*=\s*["']\d+\.\d+\.\d+["']
        | version\s*=\s*["']\d+\.\d+\.\d+["']
        | ["']Application-Version["']\]\s*=\s*["']\d+\.\d+\.\d+["']
    )""",
    re.VERBOSE,
)


@pytest.mark.parametrize(
    "path",
    ["core/api/server.py", "core/nexus/graphql.py", "core/nexus/nexus_api.py"],
)
def test_no_hardcoded_version_literals(path: str):
    """A literal here is how the drift started; catch the next one."""
    text = (ROOT / path).read_text(encoding="utf-8")
    literals = _ASSIGNS_A_VERSION.findall(text)
    assert not literals, f"{path} hardcodes {literals} — import it from core.version"


def test_no_hardcoded_user_agent_literals():
    text = (ROOT / "core/api/server.py").read_text(encoding="utf-8")
    assert "Project_ModManager_Rivals/" not in text, (
        "server.py builds a User-Agent by hand; use USER_AGENT from core.version"
    )
