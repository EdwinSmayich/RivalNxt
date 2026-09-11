"""The application version, in one place.

It used to be written out by hand in six: package.json, tauri.conf.json,
core/nexus/graphql.py, core/nexus/nexus_api.py and twice more inside
core/api/server.py as a literal in a User-Agent header. Bumping the release
meant finding all of them, and the ones in headers were routinely missed — the
app introduced itself to Nexus under a version it had not been for two releases.

package.json remains the source of truth for the JavaScript side and for the
installer; scripts/sync-version.js copies it into tauri.conf.json. This constant
is the Python side of the same number, and the test suite asserts the two agree.
"""
from __future__ import annotations

APP_VERSION = "1.0.3"

#: Sent to Nexus as User-Agent / Application-Name so their side can attribute
#: traffic to this client.
APP_NAME = "Project_ModManager_Rivals"

USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
