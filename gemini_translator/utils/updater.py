# -*- coding: utf-8 -*-
import sys
import os
import subprocess
import requests
from PyQt6.QtCore import QThread, pyqtSignal
from gemini_translator.api.config import GITHUB_REPO
from gemini_translator.version import APP_VERSION

class UpdateChecker(QThread):
    update_available = pyqtSignal(str, str, str) # version, description, download_url
    error_occurred = pyqtSignal(str)
    no_update = pyqtSignal()

    def is_source_mode(self):
        import sys, os
        is_frozen = getattr(sys, 'frozen', False)
        # Check if we are running in a git repo
        git_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "..", ".git")
        return not is_frozen and (os.path.exists('.git') or os.path.exists(git_dir))

    def run(self):
        import sys
        if getattr(sys, 'frozen', False):
            self._check_release_update()
        elif self.is_source_mode():
            self._check_source_update()
        else:
            # Source mode but without git (e.g. downloaded zip)
            self._check_commit_update()

    def _check_source_update(self):
        try:
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            fetch_res = subprocess.run(["git", "fetch"], capture_output=True, text=True, cwd=repo_root)
            if fetch_res.returncode != 0:
                self.error_occurred.emit("Ошибка при выполнении git fetch")
                return
                
            rev_res = subprocess.run(["git", "rev-list", "--count", "HEAD..@{u}"], capture_output=True, text=True, cwd=repo_root)
            if rev_res.returncode == 0:
                count = int(rev_res.stdout.strip() or "0")
                if count > 0:
                    self.update_available.emit("source", f"Доступны обновления на GitHub ({count} новых коммитов).", "")
                else:
                    self.no_update.emit()
            else:
                self.no_update.emit()
        except Exception as e:
            self.error_occurred.emit(str(e))
            
    def _check_commit_update(self):
        try:
            from PyQt6.QtCore import QSettings
            url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                latest_sha = data.get("sha")
                if not latest_sha:
                    self.no_update.emit()
                    return
                
                settings = QSettings("SiberianTeam", "TranslatorFork")
                installed_commit = settings.value("updater/installed_commit", "")
                
                if not installed_commit:
                    # First run from source ZIP, silently save the commit to track future updates
                    settings.setValue("updater/installed_commit", latest_sha)
                    settings.sync()
                    self.no_update.emit()
                    return
                
                if installed_commit != latest_sha:
                    commit_msg = data.get("commit", {}).get("message", "Доступно обновление исходного кода.")
                    body = f"Найден новый коммит:\n{commit_msg}"
                    zip_url = f"https://api.github.com/repos/{GITHUB_REPO}/zipball/main"
                    self.update_available.emit(latest_sha, body, f"source_zip:{zip_url}")
                else:
                    self.no_update.emit()
            else:
                self.error_occurred.emit(f"Ошибка API GitHub: {response.status_code}")
        except Exception as e:
            self.error_occurred.emit(str(e))

    def _check_release_update(self):
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            # Disable verify=False if possible, but keep simple timeout
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                latest_version = data.get("tag_name", "").lstrip("v")
                current_version = APP_VERSION.lstrip("v")
                
                # Basic version comparison
                import re
                def parse_version(v):
                    return [int(x) for x in re.findall(r'\d+', v)]
                
                latest_parsed = parse_version(latest_version)
                current_parsed = parse_version(current_version)
                
                if latest_parsed > current_parsed:
                    body = data.get("body", "Доступно новое обновление.")

                    assets = data.get("assets", [])
                    download_url = ""
                    
                    dmg_url = None
                    zip_url = None
                    # Try to find the right asset for the platform
                    for asset in assets:
                        name = asset["name"].lower()
                        if sys.platform == "win32" and name.endswith(".exe"):
                            download_url = asset["browser_download_url"]
                            break
                        elif sys.platform == "darwin":
                            if name.endswith(".dmg"):
                                dmg_url = asset["browser_download_url"]
                            elif name.endswith(".zip"):
                                zip_url = asset["browser_download_url"]
                                
                    if sys.platform == "darwin":
                        download_url = dmg_url or zip_url
                    
                    # Fallback to first asset if platform specific is not found
                    if not download_url and assets:
                        download_url = assets[0]["browser_download_url"]
                        
                    self.update_available.emit(latest_version, body, download_url)
                else:
                    self.no_update.emit()
            else:
                self.error_occurred.emit(f"HTTP {response.status_code}")
        except Exception as e:
            self.error_occurred.emit(str(e))
