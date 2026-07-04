from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class PythonRuntimeManager:
    """Discovers a user Python and performs an explicitly requested official install."""

    def __init__(self, database: Any, workspace: Path) -> None:
        self.database = database
        self.workspace = workspace
        self._lock = threading.Lock()
        self._install: dict[str, Any] = {
            "status": "idle", "detail": "Python has not been checked yet.", "progress": 0.0, "error": None,
        }

    @staticmethod
    def _verify(executable: str) -> tuple[str, str] | None:
        try:
            completed = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        version = (completed.stdout or completed.stderr).strip()
        if completed.returncode != 0 or not version.startswith("Python 3."):
            return None
        try:
            resolved = subprocess.run(
                [executable, "-c", "import sys;print(sys.executable)"], capture_output=True,
                text=True, timeout=5, creationflags=CREATE_NO_WINDOW,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            resolved = executable
        return str(Path(resolved or executable).resolve()), version

    def status(self) -> dict[str, Any]:
        custom = str(self.database.setting("python_executable", "") or "").strip()
        candidates = [custom] if custom else []
        for discovered in filter(None, [shutil.which("python"), shutil.which("python3")]):
            # Windows App Execution Aliases may install a runtime simply by
            # being launched. Detection must never trigger installation.
            if "windowsapps" not in str(discovered).casefold():
                candidates.append(str(discovered))
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        search_roots = [
            local_app_data / "Python",
            local_app_data / "Programs" / "Python",
            Path("C:/"),
        ]
        patterns = ["pythoncore-*/python.exe", "Python*/python.exe", "Python3*/python.exe"]
        for root in search_roots:
            for pattern in patterns:
                candidates.extend(str(path) for path in root.glob(pattern) if path.is_file())
        checked: set[str] = set()
        for candidate in candidates:
            normalized = os.path.normcase(str(candidate))
            if normalized in checked:
                continue
            checked.add(normalized)
            result = self._verify(str(candidate))
            if result:
                path, version = result
                return {
                    "available": True, "path": path, "version": version,
                    "source": "custom" if custom else "detected", **self._install,
                }
        return {
            "available": False, "path": custom, "version": None, "source": "custom" if custom else "missing",
            **self._install,
        }

    def set_custom(self, path: str) -> dict[str, Any]:
        candidate = str(Path(path.strip().strip('"')).expanduser())
        result = self._verify(candidate)
        if not result:
            raise ValueError("That file is not a working Python 3 interpreter")
        self.database.set_setting("python_executable", result[0])
        return self.status()

    def start_install(self) -> dict[str, Any]:
        if self._install["status"] in {"installing_manager", "installing_runtime"}:
            return self.status()
        with self._lock:
            self._install = {
                "status": "installing_manager", "detail": "Installing Python's official Windows manager…",
                "progress": 0.1, "error": None,
            }
        threading.Thread(target=self._install_worker, daemon=True).start()
        return self.status()

    def _run_install(self, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )

    def _install_worker(self) -> None:
        try:
            winget = shutil.which("winget")
            if not winget:
                raise RuntimeError("WinGet is unavailable. Open the official Python download page instead.")
            manager = self._run_install([
                winget, "install", "9NQ7512CXL7T", "-e", "--accept-package-agreements",
                "--accept-source-agreements", "--disable-interactivity",
            ], 600)
            if manager.returncode not in {0, -1978335189}:  # success or already installed
                detail = (manager.stderr or manager.stdout)[-1000:].strip()
                raise RuntimeError(detail or "Python Install Manager could not be installed")
            self._install.update({
                "status": "installing_runtime", "detail": "Installing the current Python 3 runtime…", "progress": 0.55,
            })
            launcher = shutil.which("pymanager") or shutil.which("py")
            if not launcher:
                windows_apps = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
                launcher = next((str(path) for name in ("pymanager.exe", "py.exe") for path in windows_apps.glob(name)), None)
            if not launcher:
                raise RuntimeError("Python's manager was installed. Restart Local Agent Studio, then press Check again.")
            runtime = self._run_install([launcher, "install", "-y", "3.14"], 1200)
            if runtime.returncode != 0:
                detail = (runtime.stderr or runtime.stdout)[-1000:].strip()
                raise RuntimeError(detail or "The Python runtime could not be installed")
            detected = self.status()
            if not detected["available"]:
                # The current process may not receive refreshed aliases until restart.
                self._install.update({
                    "status": "ready_restart", "detail": "Python is installed. Restart the app to finish detection.",
                    "progress": 1.0,
                })
            else:
                self._install.update({"status": "ready", "detail": "Python is ready.", "progress": 1.0})
        except Exception as error:
            self._install.update({"status": "failed", "detail": "Python setup did not finish.", "error": str(error)})

    def execute(self, code: str, input_value: Any, timeout_seconds: int = 30) -> dict[str, Any]:
        runtime = self.status()
        if not runtime["available"]:
            raise RuntimeError("Install or select Python before adding a Python function")
        if not code.strip() or len(code) > 50_000:
            raise ValueError("Python code must be between 1 and 50,000 characters")
        timeout_seconds = max(1, min(int(timeout_seconds), 60))
        self.workspace.mkdir(parents=True, exist_ok=True)
        environment = {
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "TEMP": tempfile.gettempdir(), "TMP": tempfile.gettempdir(),
            "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
        }
        script_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix="studio_", dir=self.workspace,
                encoding="utf-8", delete=False,
            ) as script:
                script.write(code)
                script_path = Path(script.name)
            completed = subprocess.run(
                [runtime["path"], "-I", "-u", str(script_path)],
                input=json.dumps(input_value, ensure_ascii=False), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout_seconds,
                cwd=self.workspace, env=environment, creationflags=CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"Python exceeded the {timeout_seconds}-second limit") from error
        finally:
            if script_path:
                script_path.unlink(missing_ok=True)
        stdout = completed.stdout[-262_144:]
        stderr = completed.stderr[-65_536:]
        if completed.returncode != 0:
            raise RuntimeError(f"Python exited with code {completed.returncode}: {stderr or stdout}")
        return {"stdout": stdout, "stderr": stderr, "exit_code": completed.returncode}
