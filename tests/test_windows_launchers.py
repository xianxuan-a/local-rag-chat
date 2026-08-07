from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
CMD_FILES = ("启动项目.cmd", "停止项目.cmd", "查看状态.cmd")
WINDOWS = sys.platform == "win32"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("name", CMD_FILES)
def test_cmd_wrapper_is_location_independent_and_propagates_exit_code(name: str) -> None:
    content = _text(PROJECT_ROOT / name).casefold()

    assert "%~dp0scripts\\" in content
    assert "powershell.exe -noprofile -executionpolicy bypass -file" in content
    assert "%*" in content
    assert "exit /b %local_rag_exit_code%" in content
    assert "pause" not in content


def test_start_contract_is_real_atomic_and_rolls_back() -> None:
    start = _text(SCRIPTS / "start_local.ps1")
    common = _text(SCRIPTS / "local_runtime.ps1")

    assert '"dev:real"' in start
    assert '$env:HOST = "127.0.0.1"' in start
    assert "$env:VITE_API_MODE = \"real\"" in start
    assert "dev:mock" not in start.casefold()
    assert "Stop-LocalServiceRecord" in start
    assert 'New-LaunchState -Phase "running"' in start
    assert "Write-LocalJsonAtomic" in start
    assert "[System.IO.File]::Replace" in common
    assert "System.Threading.Mutex" in common
    assert "Test-LocalProcessDescendantOf" in common


def test_stop_contract_never_kills_by_port_or_uses_recursive_delete() -> None:
    stop = _text(SCRIPTS / "stop_local.ps1").casefold()
    all_launchers = "\n".join(
        _text(path).casefold()
        for path in (
            SCRIPTS / "local_runtime.ps1",
            SCRIPTS / "start_local.ps1",
            SCRIPTS / "stop_local.ps1",
            SCRIPTS / "status_local.ps1",
            SCRIPTS / "init_local_runtime.ps1",
        )
    )

    assert "stop-localservicerecord" in stop
    assert "stop-process" not in stop
    assert "taskkill" not in all_launchers
    for forbidden in (
        "remove-item -recurse",
        "rm -rf",
        "rmdir /s",
        "rd /s",
        "del /s",
    ):
        assert forbidden not in all_launchers


@pytest.mark.skipif(not WINDOWS, reason="requires Windows PowerShell 5.1")
def test_powershell_51_parses_every_local_launcher() -> None:
    paths = sorted(SCRIPTS.glob("*local*.ps1"))
    quoted = ",".join("'" + str(path).replace("'", "''") + "'" for path in paths)
    command = (
        "$failed=$false;"
        f"@({quoted})|ForEach-Object{{"
        "$t=$null;$e=$null;"
        "[void][Management.Automation.Language.Parser]::ParseFile($_,[ref]$t,[ref]$e);"
        "if($e.Count){$failed=$true;$e|ForEach-Object{Write-Error $_}}};"
        "if($failed){exit 1}"
    )

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=Path(os.environ["SystemRoot"]) / "System32",
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode(
        "utf-8", errors="replace"
    )


def _copy_launcher_fixture(target: Path) -> None:
    scripts = target / "scripts"
    scripts.mkdir(parents=True)
    for name in ("local_runtime.ps1", "start_local.ps1", "stop_local.ps1", "status_local.ps1"):
        shutil.copyfile(SCRIPTS / name, scripts / name)
    for name in CMD_FILES:
        shutil.copyfile(PROJECT_ROOT / name, target / name)


def _write_runtime_identity(project: Path) -> Path:
    runtime = project / "runtime data"
    runtime.mkdir()
    database = runtime / "metadata" / "runtime.db"
    database.parent.mkdir()
    database.touch()
    runtime_id = "windows-launcher-test-runtime"
    (runtime / ".local-rag-runtime.json").write_text(
        json.dumps({"runtime_id": runtime_id}), encoding="utf-8"
    )
    (project / ".local-rag-chat.json").write_text(
        json.dumps(
            {
                "runtime_id": runtime_id,
                "runtime_root": str(runtime),
                "database_path": str(database),
            }
        ),
        encoding="utf-8",
    )
    return runtime


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _make_runnable_fixture(project: Path) -> tuple[Path, Path]:
    _copy_launcher_fixture(project)
    runtime = _write_runtime_identity(project)
    (project / ".env").write_text("", encoding="utf-8")
    frontend = project / "frontend"
    (frontend / "node_modules").mkdir(parents=True)
    (project / "run.py").write_text(
        """from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({"data": {"status": "ready"}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
    def log_message(self, *args):
        pass

ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
""",
        encoding="utf-8",
    )
    (project / "scripts" / "prepare_local_database.py").write_text(
        'print(\'{"current":"test","head":"test","upgrade_required":false}\')\n',
        encoding="utf-8",
    )
    (frontend / "frontend_server.py").write_text(
        """from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import sys

port = int(sys.argv[1])
ThreadingHTTPServer(("127.0.0.1", port), SimpleHTTPRequestHandler).serve_forever()
""",
        encoding="utf-8",
    )
    npm = project / "npm.cmd"
    npm.write_text(
        '@echo off\r\n"%LOCAL_RAG_LAUNCHER_TEST_PYTHON%" '
        '"%~dp0frontend\\frontend_server.py" %7\r\n',
        encoding="ascii",
    )
    return runtime, npm


def _run_cmd(path: Path, *arguments: str, timeout: int = 45) -> subprocess.CompletedProcess[bytes]:
    argument_line = subprocess.list2cmdline(list(arguments))
    command_line = f'cmd.exe /d /s /c ""{path}"'
    if argument_line:
        command_line += f" {argument_line}"
    command_line += '"'
    environment = os.environ.copy()
    environment["LOCAL_RAG_LAUNCHER_TEST_PYTHON"] = sys.executable
    return subprocess.run(
        command_line,
        cwd=Path(os.environ["SystemRoot"]) / "System32",
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )


def _wait_port_closed(port: int) -> bool:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return True
        time.sleep(0.1)
    return False


@pytest.mark.skipif(not WINDOWS, reason="requires cmd.exe and Windows PowerShell")
def test_cmd_runs_from_outside_repo_with_chinese_and_spaces(tmp_path: Path) -> None:
    project = tmp_path / "中文 空格 launcher"
    project.mkdir()
    _copy_launcher_fixture(project)
    _write_runtime_identity(project)

    result = _run_cmd(project / "查看状态.cmd")

    assert result.returncode == 3


@pytest.mark.skipif(not WINDOWS, reason="requires cmd.exe and Windows PowerShell")
def test_missing_env_fails_before_process_start(tmp_path: Path) -> None:
    project = tmp_path / "missing env project"
    project.mkdir()
    _copy_launcher_fixture(project)
    runtime = _write_runtime_identity(project)

    result = _run_cmd(project / "启动项目.cmd", "-NoBrowser", "-AutoUpgrade")

    assert result.returncode == 1
    assert not (runtime / ".local-rag-launch-state.json").exists()


@pytest.mark.skipif(not WINDOWS, reason="requires Get-NetTCPConnection")
def test_port_conflict_does_not_stop_unknown_owner(tmp_path: Path) -> None:
    project = tmp_path / "port conflict project"
    project.mkdir()
    _copy_launcher_fixture(project)
    runtime = _write_runtime_identity(project)
    (project / ".env").write_text("", encoding="utf-8")
    python_path = project / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.touch()
    (project / "frontend" / "node_modules").mkdir(parents=True)
    (project / "run.py").write_text("", encoding="utf-8")
    fake_npm = project / "npm.cmd"
    fake_npm.write_text("@exit /b 1\n", encoding="ascii")

    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        backend_port = occupied.getsockname()[1]
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            frontend_port = candidate.getsockname()[1]

        result = _run_cmd(
            project / "启动项目.cmd",
            "-NoBrowser",
            "-AutoUpgrade",
            "-BackendPort",
            str(backend_port),
            "-FrontendPort",
            str(frontend_port),
            "-NpmPath",
            str(fake_npm),
        )

        assert result.returncode == 1
        assert occupied.fileno() >= 0
        assert not (runtime / ".local-rag-launch-state.json").exists()


@pytest.mark.skipif(not WINDOWS, reason="requires Windows process identity APIs")
def test_stop_skips_reused_pid_and_clears_stale_state(tmp_path: Path) -> None:
    project = tmp_path / "stale pid project"
    project.mkdir()
    _copy_launcher_fixture(project)
    runtime = _write_runtime_identity(project)
    state = {
        "schema_version": 2,
        "launch_id": "stale-test",
        "phase": "running",
        "project_root": str(project),
        "runtime_root": str(runtime),
        "runtime_id": "windows-launcher-test-runtime",
        "backend_port": 19998,
        "frontend_port": 19999,
        "services": [
            {
                "name": "backend",
                "port": 19998,
                "process": {
                    "process_id": os.getpid(),
                    "start_time_utc": "2000-01-01T00:00:00.0000000Z",
                    "executable_path": str(Path(sys.executable).resolve()),
                    "command_line": "intentionally stale",
                },
                "launcher": None,
            }
        ],
    }
    state_path = runtime / ".local-rag-launch-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = _run_cmd(project / "停止项目.cmd")

    assert result.returncode == 0
    assert os.getpid() > 0
    assert not state_path.exists()


@pytest.mark.skipif(not WINDOWS, reason="requires Windows process and port APIs")
def test_success_duplicate_status_and_repeated_stop(tmp_path: Path) -> None:
    project = tmp_path / "完整 启停 project"
    project.mkdir()
    runtime, npm = _make_runnable_fixture(project)
    backend_port = _free_port()
    frontend_port = _free_port()
    while frontend_port == backend_port:
        frontend_port = _free_port()
    start_args = (
        "-NoBrowser",
        "-AutoUpgrade",
        "-BackendPort",
        str(backend_port),
        "-FrontendPort",
        str(frontend_port),
        "-PythonExecutable",
        sys.executable,
        "-NpmPath",
        str(npm),
        "-StartupTimeoutSeconds",
        "20",
    )

    try:
        first = _run_cmd(project / "启动项目.cmd", *start_args)
        assert first.returncode == 0
        duplicate = _run_cmd(project / "启动项目.cmd", *start_args)
        assert duplicate.returncode == 0
        status = _run_cmd(project / "查看状态.cmd")
        assert status.returncode == 0
    finally:
        stopped = _run_cmd(project / "停止项目.cmd")

    assert stopped.returncode == 0
    assert _run_cmd(project / "停止项目.cmd").returncode == 0
    assert _wait_port_closed(backend_port)
    assert _wait_port_closed(frontend_port)
    assert not (runtime / ".local-rag-launch-state.json").exists()


@pytest.mark.skipif(not WINDOWS, reason="requires Windows process and port APIs")
def test_frontend_failure_rolls_back_backend_and_state(tmp_path: Path) -> None:
    project = tmp_path / "前端失败 rollback project"
    project.mkdir()
    runtime, _npm = _make_runnable_fixture(project)
    backend_port = _free_port()
    frontend_port = _free_port()
    failing_command = shutil.which("where.exe")
    assert failing_command is not None

    result = _run_cmd(
        project / "启动项目.cmd",
        "-NoBrowser",
        "-AutoUpgrade",
        "-BackendPort",
        str(backend_port),
        "-FrontendPort",
        str(frontend_port),
        "-PythonExecutable",
        sys.executable,
        "-NpmPath",
        failing_command,
        "-StartupTimeoutSeconds",
        "20",
    )

    assert result.returncode == 1
    assert _wait_port_closed(backend_port)
    assert _wait_port_closed(frontend_port)
    assert not (runtime / ".local-rag-launch-state.json").exists()
