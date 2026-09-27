"""Shutdown-path tests for the cross-platform development runner."""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

import dev_runner


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = None
        self.stderr = None

    def poll(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_shutdown_state():
    dev_runner._shutdown_requested = False
    dev_runner._shutdown_in_progress = False
    yield
    dev_runner._shutdown_requested = False
    dev_runner._shutdown_in_progress = False


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".env").write_text("SESSION_SECRET_KEY=test\n", encoding="utf-8")
    monkeypatch.setattr(dev_runner, "ROOT", tmp_path)
    monkeypatch.setattr(dev_runner, "_required_command", lambda name: f"/bin/{name}")
    return tmp_path


def test_signal_before_the_drain_requests_shutdown() -> None:
    with pytest.raises(KeyboardInterrupt):
        dev_runner._handle_shutdown_signal(signal.SIGINT, None)
    assert dev_runner._shutdown_requested is True
    assert dev_runner._shutdown_in_progress is False


def test_signal_during_the_drain_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _FakeProcess()
    frontend = _FakeProcess()
    stopped: list[object] = []

    def _stop(process: object) -> None:
        stopped.append(process)
        if len(stopped) == 1:
            # The first-ever signal lands after the drain has already begun.
            dev_runner._handle_shutdown_signal(signal.SIGINT, None)

    monkeypatch.setattr(dev_runner, "_stop_process", _stop)
    dev_runner._drain(cast("Any", (backend, frontend)))

    assert stopped == [backend, frontend]
    assert dev_runner._shutdown_in_progress is True
    assert dev_runner._shutdown_requested is False


def test_drain_marks_shutdown_before_touching_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[bool] = []
    monkeypatch.setattr(
        dev_runner,
        "_stop_process",
        lambda process: observed.append(dev_runner._shutdown_in_progress),
    )
    dev_runner._drain(cast("Any", (_FakeProcess(), None, _FakeProcess())))
    assert observed == [True, True]


def test_main_drains_when_an_unrelated_exception_unwinds(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _FakeProcess()
    frontend = _FakeProcess()
    failure = RuntimeError("stream reader exploded")
    stopped: list[object] = []

    def _stop(process: object) -> None:
        stopped.append(process)
        if len(stopped) == 1:
            dev_runner._handle_shutdown_signal(signal.SIGTERM, None)

    monkeypatch.setattr(
        dev_runner, "_start", MagicMock(side_effect=[backend, frontend])
    )
    monkeypatch.setattr(dev_runner, "_wait_for_exit", MagicMock(side_effect=failure))
    monkeypatch.setattr(dev_runner, "_stop_process", _stop)

    with pytest.raises(RuntimeError) as raised:
        dev_runner.main()

    assert raised.value is failure
    assert stopped == [backend, frontend]
    assert dev_runner._shutdown_in_progress is True


def test_main_returns_130_and_drains_on_interrupt(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _FakeProcess()
    frontend = _FakeProcess()
    stopped: list[object] = []
    monkeypatch.setattr(
        dev_runner,
        "_start",
        MagicMock(side_effect=[backend, frontend]),
    )
    monkeypatch.setattr(
        dev_runner, "_wait_for_exit", MagicMock(side_effect=KeyboardInterrupt)
    )
    monkeypatch.setattr(dev_runner, "_stop_process", stopped.append)

    assert dev_runner.main() == 130
    assert stopped == [backend, frontend]


def test_main_drains_a_partially_started_pair(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _FakeProcess()
    stopped: list[object] = []
    monkeypatch.setattr(
        dev_runner,
        "_start",
        MagicMock(side_effect=[backend, OSError("pnpm could not be started")]),
    )
    monkeypatch.setattr(dev_runner, "_stop_process", stopped.append)

    assert dev_runner.main() == 127
    assert stopped == [backend]


def test_main_requires_an_environment_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dev_runner, "ROOT", tmp_path)
    installed = MagicMock(return_value={})
    monkeypatch.setattr(dev_runner, "_install_signal_handlers", installed)

    assert dev_runner.main() == 2
    installed.assert_not_called()


def test_signal_handlers_are_restored_after_main(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _FakeProcess()
    frontend = _FakeProcess()
    before = signal.getsignal(signal.SIGINT)
    monkeypatch.setattr(
        dev_runner, "_start", MagicMock(side_effect=[backend, frontend])
    )
    monkeypatch.setattr(dev_runner, "_wait_for_exit", MagicMock(return_value=3))
    monkeypatch.setattr(dev_runner, "_stop_process", lambda process: None)

    assert dev_runner.main() == 3
    assert signal.getsignal(signal.SIGINT) is before
