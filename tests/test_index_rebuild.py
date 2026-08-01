import threading
import time

import pytest

from rag.index_rebuild import BlueGreenIndexCoordinator, IndexRebuildError


class Backend:
    def __init__(self, fail_switch=False):
        self.calls = []
        self.fail_switch = fail_switch

    def switch_active_alias(self, **kwargs):
        self.calls.append(("switch", kwargs))
        if self.fail_switch:
            raise RuntimeError("switch failed")

    def rollback_active_alias(self, **kwargs):
        self.calls.append(("rollback", kwargs))


def test_rebuild_validates_before_atomic_switch():
    backend = Backend()
    result = BlueGreenIndexCoordinator(backend).rebuild(
        previous_collection="stable-1",
        build_candidate=lambda: "build-2",
        validate_candidate=lambda collection: collection == "build-2",
    )
    assert result == "build-2"
    assert [name for name, _ in backend.calls] == ["switch"]


def test_rebuild_rejects_candidate_without_touching_alias():
    backend = Backend()
    with pytest.raises(IndexRebuildError, match="rejected"):
        BlueGreenIndexCoordinator(backend).rebuild(
            previous_collection="stable-1",
            build_candidate=lambda: "build-2",
            validate_candidate=lambda _: False,
        )
    assert backend.calls == []


def test_rebuild_rolls_back_when_activation_fails():
    backend = Backend(fail_switch=True)
    with pytest.raises(IndexRebuildError, match="activation failed"):
        BlueGreenIndexCoordinator(backend).rebuild(
            previous_collection="stable-1",
            build_candidate=lambda: "build-2",
            validate_candidate=lambda _: True,
        )
    assert [name for name, _ in backend.calls] == ["switch", "rollback"]


def test_rebuild_times_out_a_blocking_builder():
    backend = Backend()

    def slow_builder():
        time.sleep(0.1)
        return "build-2"

    with pytest.raises(IndexRebuildError, match="timeout"):
        BlueGreenIndexCoordinator(backend, timeout_seconds=0.01).rebuild(
            previous_collection="stable-1",
            build_candidate=slow_builder,
            validate_candidate=lambda _: True,
        )
    assert backend.calls == []


def test_validation_timeout_never_switches_unverified_candidate():
    backend = Backend()
    release = threading.Event()

    def slow_validation(_candidate):
        release.wait(1)
        return True

    try:
        with pytest.raises(IndexRebuildError, match="timeout"):
            BlueGreenIndexCoordinator(backend, timeout_seconds=0.01).rebuild(
                previous_collection="stable-1",
                build_candidate=lambda: "build-2",
                validate_candidate=slow_validation,
            )
        assert backend.calls == []
    finally:
        release.set()


def test_cleanup_runs_after_activation_and_failure_keeps_new_alias():
    backend = Backend()
    with pytest.raises(IndexRebuildError, match="cleanup"):
        BlueGreenIndexCoordinator(backend, timeout_seconds=0.05).rebuild(
            previous_collection="stable-1",
            build_candidate=lambda: "build-2",
            validate_candidate=lambda _: True,
            cleanup_old_collections=lambda: (_ for _ in ()).throw(RuntimeError("disk")),
        )
    assert [name for name, _ in backend.calls] == ["switch"]
