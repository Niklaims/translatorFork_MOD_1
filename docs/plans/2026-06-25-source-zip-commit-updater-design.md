# Design: Source ZIP Updater via GitHub Commits

## Overview
Currently, if a user runs the application from source code but without a `.git` folder (e.g. downloaded the ZIP of the `main` branch from GitHub), the application falls back to checking GitHub Releases. Because the `main` branch usually has `APP_VERSION="dev"`, this triggers constant false-positive update prompts to older releases.

This design introduces a mechanism to track updates based on GitHub **commits** instead of releases for users running from a source ZIP.

## Logic Flow
1. **Detection:** When `is_source_mode` is True (no `sys.frozen`) but there is no `.git` folder, we activate the "source ZIP" update mode instead of falling back to release updates.
2. **Fetch Latest Commit:** The updater calls `https://api.github.com/repos/Rasteo123/translatorFork_MOD/commits/main` to get the latest commit `sha`.
3. **Check Local State:** The updater reads `updater/installed_commit` from `QSettings`.
4. **First Run Scenario:** If `installed_commit` is empty, we silently set `installed_commit` to the fetched `sha` and do NOT prompt for an update. This handles the case where the user just downloaded the ZIP and we don't know exactly which commit they have.
5. **Update Available Scenario:** If `installed_commit` is present and does not match the fetched `sha`, we emit `update_available` with the text `source_zip:https://api.github.com/repos/Rasteo123/translatorFork_MOD/zipball/main`.
6. **Installation:** When the user clicks "Download and Install", the existing `download_source_zip_update` logic runs.
7. **Completion:** The `launch_source_zip_updater` function modifies the extraction script to save the *new* `sha` to `updater/installed_commit` after successful extraction, ensuring the cycle continues correctly.

## Edge Cases
- **No Internet:** API call fails, updater silently finishes or reports error if manually triggered.
- **GitHub API Rate Limits:** Handled gracefully by existing request logic (fail silently).
- **Paths with Spaces/Cyrillic:** Already handled correctly by the `source_zip` extractor script.
