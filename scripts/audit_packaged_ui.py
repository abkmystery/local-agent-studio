from __future__ import annotations

import argparse
import base64
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from websockets.sync.client import connect


ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(url: str, token: str, method: str = "GET", body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"x-studio-token": token, "content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def wait_json(url: str, token: str | None = None, seconds: int = 90) -> Any:
    deadline = time.monotonic() + seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if token:
                return http_json(url, token)
            with urllib.request.urlopen(url, timeout=2) as response:
                return json.loads(response.read())
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            last_error = error
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def stop_tree(process: subprocess.Popen[Any] | None) -> None:
    if not process or process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


class CDP:
    def __init__(self, url: str) -> None:
        self.socket = connect(url, open_timeout=10, close_timeout=2)
        self.identifier = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.identifier += 1
        identifier = self.identifier
        self.socket.send(json.dumps({"id": identifier, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.socket.recv(timeout=15))
            if message.get("id") != identifier:
                continue
            if "error" in message:
                raise RuntimeError(message["error"].get("message", str(message["error"])))
            return message.get("result", {})

    def evaluate(self, expression: str) -> Any:
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"].get("text", "Renderer expression failed"))
        return result.get("result", {}).get("value")

    def wait_text(self, text: str, seconds: int = 15) -> None:
        deadline = time.monotonic() + seconds
        encoded = json.dumps(text)
        while time.monotonic() < deadline:
            if self.evaluate(f"document.body.innerText.includes({encoded})"):
                return
            time.sleep(0.1)
        visible = self.evaluate("document.body.innerText.slice(0,1200)")
        raise RuntimeError(f"Timed out waiting for visible text: {text}\nVisible text:\n{visible}")

    def click_button(self, text: str) -> None:
        encoded = json.dumps(text)
        clicked = self.evaluate(
            "(() => { const items=Array.from(document.querySelectorAll('button'));"
            f"const item=items.find(x=>x.textContent.trim()==={encoded})||items.find(x=>x.textContent.includes({encoded}));"
            "if(!item)return false;item.click();return true;})()"
        )
        if not clicked:
            raise RuntimeError(f"Button not found: {text}")

    def close(self) -> None:
        self.socket.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=ROOT / "release/win-unpacked/Local Agent Studio.exe")
    parser.add_argument(
        "--backend", type=Path,
        default=ROOT / ".build/backend-dist/local-agent-backend/local-agent-backend.exe",
    )
    parser.add_argument("--screenshot", type=Path, default=Path(tempfile.gettempdir()) / "local-agent-studio-ui-audit.png")
    arguments = parser.parse_args()
    if not arguments.app.is_file() or not arguments.backend.is_file():
        raise SystemExit("Build the packaged app and backend before running this audit")

    api_port, debug_port = free_port(), free_port()
    token = "ui-audit-token"
    profile = Path(tempfile.mkdtemp(prefix="local-agent-studio-ui-"))
    backend_copy = profile / "seed-backend"
    shutil.copytree(arguments.backend.parent, backend_copy)
    seed: subprocess.Popen[Any] | None = None
    desktop: subprocess.Popen[Any] | None = None
    cdp: CDP | None = None
    checks: list[str] = []
    started = time.monotonic()
    api = f"http://127.0.0.1:{api_port}"

    try:
        (profile / "models").mkdir()
        (profile / "models/qa.gguf").write_bytes(b"")
        seed = subprocess.Popen([
            str(backend_copy / "local-agent-backend.exe"), "--host", "127.0.0.1",
            "--port", str(api_port), "--data-dir", str(profile), "--auth-token", token,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        wait_json(f"{api}/health", token, 30)
        http_json(f"{api}/api/settings", token, "PUT", {"onboarding_complete": True})
        agent = http_json(f"{api}/api/agents", token, "POST", {
            "name": "QA Writer", "description": "UI audit agent", "provider_id": "llama_cpp",
            "model_id": "qa.gguf", "instructions": "Write concise test output.",
            "config": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 64},
        })
        del agent
        workflow = http_json(f"{api}/api/workflows", token, "POST", {
            "name": "Run visibility", "description": "Completed run for the Runs screen.",
            "spec": {"version": "1.0", "limits": {"max_iterations": 2, "timeout_seconds": 30},
                     "nodes": [{"id": "input", "type": "input", "label": "Input", "position": {"x": 80, "y": 160}, "config": {}},
                               {"id": "output", "type": "output", "label": "Output", "position": {"x": 430, "y": 160}, "config": {}}],
                     "edges": [{"id": "e1", "source": "input", "target": "output"}]},
        })
        run = http_json(f"{api}/api/workflows/{workflow['id']}/run", token, "POST", {"input": "Visible completed run"})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if http_json(f"{api}/api/runs/{run['id']}", token)["status"] == "completed":
                break
            time.sleep(0.1)
        http_json(f"{api}/api/workflows", token, "POST", {
            "name": "Delete me", "description": "Used to verify deletion.",
            "spec": {"version": "1.0", "nodes": [{"id": "input", "type": "input", "label": "Input", "position": {}, "config": {}},
                                                       {"id": "output", "type": "output", "label": "Output", "position": {}, "config": {}}],
                     "edges": [{"id": "e1", "source": "input", "target": "output"}]},
        })
        stop_tree(seed)
        seed = None

        desktop = subprocess.Popen([
            str(arguments.app), f"--user-data-dir={profile}", f"--remote-debugging-port={debug_port}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 90
        target = None
        while time.monotonic() < deadline:
            targets = wait_json(f"http://127.0.0.1:{debug_port}/json/list", seconds=5)
            target = next((item for item in targets if item.get("type") == "page"), None)
            if target:
                break
            time.sleep(0.2)
        if not target:
            raise RuntimeError("Electron renderer target did not appear")
        cdp = CDP(target["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.wait_text("Build something useful", 20)
        cdp.evaluate("window.__qaErrors=[];window.addEventListener('error',e=>window.__qaErrors.push(e.message));true")
        checks.append("Home")

        for navigation, heading in (("Models", "Models"), ("Agents", "Agents")):
            cdp.click_button(navigation); cdp.wait_text(heading); checks.append(navigation)
        cdp.click_button("New agent"); cdp.wait_text("Skill files"); cdp.wait_text("Agent permissions")
        assert cdp.evaluate("Boolean(document.querySelector('input[type=file][accept*=\".md\"]'))")
        cdp.evaluate("document.querySelector('button[aria-label=\"Close\"]').click();true")
        checks.append("Agent modal")

        cdp.click_button("Workflows"); cdp.wait_text("Workflows"); cdp.wait_text("Delete me")
        assert cdp.evaluate("Boolean(document.querySelector('.run-composer input[type=file][accept*=\".png\"]'))")
        assert cdp.evaluate("Boolean(document.querySelector('.local-path-row textarea'))")
        cdp.click_button("Router"); cdp.evaluate("document.querySelector('.react-flow__node.type-router').click();true")
        cdp.wait_text("Text rules"); cdp.click_button("Add text rule")
        assert cdp.evaluate("Boolean(document.querySelector('.router-rule input'))")
        cdp.click_button("Function"); cdp.evaluate("document.querySelector('.react-flow__node.type-function').click();true")
        cdp.wait_text("Create Word document")
        options = cdp.evaluate("Array.from(document.querySelectorAll('.inspector select option')).map(x=>x.textContent).join('|')")
        for expected in ("Create Word document", "Create Excel workbook", "Send email", "Python code", "MCP server tool"):
            assert expected in options, f"Function picker is missing {expected}"
        cdp.evaluate("window.confirm=()=>true;true"); cdp.click_button("Delete")
        cdp.wait_text("Workflow deleted."); checks.append("Workflow editor")

        cdp.click_button("Runs"); cdp.wait_text("Visible completed run"); cdp.wait_text("2/2 complete"); checks.append("Runs")
        cdp.click_button("Resources"); cdp.wait_text("Know what each local model costs"); checks.append("Resources")
        cdp.click_button("Settings"); cdp.wait_text("Email for workflows")
        for text in ("Studio capabilities", "Python functions", "Local MCP servers"):
            cdp.wait_text(text)
        checks.append("Settings")
        cdp.click_button("Restart guide"); cdp.wait_text("Your agent studio, without the setup maze", 20)
        cdp.click_button("Choose how your agents think"); cdp.wait_text("Pick an AI provider")
        assert cdp.evaluate("document.querySelectorAll('.provider-choice-grid > button').length") == 4
        cdp.click_button("Connect free-tier Gemini")
        cdp.wait_text("Connect Gemini in three small steps")
        cdp.wait_text("Open Google AI Studio and sign in")
        assert cdp.evaluate("Boolean(document.querySelector('input[type=password][placeholder*=\"AI Studio\"]'))")
        assert cdp.evaluate("Boolean(document.querySelector('a[href*=\"aistudio.google.com/app/apikey\"]'))")
        checks.append("Onboarding")

        capture = cdp.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        arguments.screenshot.write_bytes(base64.b64decode(capture["data"]))
        errors = cdp.evaluate("window.__qaErrors") or []
        if errors:
            raise RuntimeError("Renderer errors: " + "; ".join(errors))
        print(json.dumps({
            "status": "passed", "checks": checks, "duration_seconds": round(time.monotonic() - started, 1),
            "screenshot": str(arguments.screenshot),
        }, indent=2))
    finally:
        if cdp:
            try: cdp.close()
            except Exception: pass
        stop_tree(desktop)
        stop_tree(seed)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
