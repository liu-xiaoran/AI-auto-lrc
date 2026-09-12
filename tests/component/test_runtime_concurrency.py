"""Runtime concurrency regression gates."""

import os
import subprocess
import sys
import tempfile
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
import torch
import torch.nn.functional as F

from t2l.adapters import legacy_v1_inference as legacy
from t2l.adapters.assets import MaterializedAssetSet
from t2l.adapters.lyrics import OfflineG2PProvider
from t2l.errors import CheckpointError
from t2l.phonetic import PhoneticConverter

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.component


class _EmptyModel(torch.nn.Module):
    def forward(self, value):
        return value


class _Resolved:
    path = Path("validated-checkpoint")


class _Locator:
    def resolve(self, spec):
        return _Resolved()


def test_conc_003_model_initialization_failure_is_cached_per_runtime(
    monkeypatch,
):
    """CONC-003: one failing initialization, identical waiters, fresh retry only."""

    attempts = 0
    attempts_lock = threading.Lock()
    failure = CheckpointError(
        "fixture checkpoint failed",
        code="T2L_MODEL_LOAD_FIXTURE",
        details={"logical_name": "Baseline"},
    )

    def load_state(path, spec):
        nonlocal attempts
        with attempts_lock:
            attempts += 1
            attempt = attempts
        if attempt == 1:
            raise failure
        return {}

    monkeypatch.setattr(legacy, "load_checkpoint_state", load_state)
    monkeypatch.setattr(legacy, "_create_model", lambda architecture: _EmptyModel())

    runtime = legacy.LegacyV1Inference(
        asset_locator=_Locator(), profile=legacy.load_legacy_v1_profile()
    )
    workers = 16
    start = threading.Barrier(workers + 1)

    def initialize():
        start.wait()
        try:
            runtime.load_model("Baseline")
        except CheckpointError as exc:  # captured for cross-waiter identity checks
            return exc
        return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(initialize) for _ in range(workers)]
        start.wait()
        results = [future.result(timeout=2) for future in futures]

    assert attempts == 1
    assert all(result is failure for result in results)
    assert all(result.code == failure.code for result in results)
    assert all(result.details == failure.details for result in results)

    with pytest.raises(CheckpointError) as repeated:
        runtime.load_model("Baseline")
    assert repeated.value is failure
    assert attempts == 1

    fresh_runtime = legacy.LegacyV1Inference(
        asset_locator=_Locator(), profile=legacy.load_legacy_v1_profile()
    )
    assert isinstance(fresh_runtime.load_model("Baseline"), _EmptyModel)
    assert attempts == 2


def test_phonetic_initialization_failure_is_cached_per_runtime(tmp_path):
    """LID provider failure is sticky only in its owning runtime."""

    attempts = 0
    attempts_lock = threading.Lock()
    failure = RuntimeError("fixture LID initialization failed")

    class Model:
        def predict(self, text, k):
            return (("__label__en",), (0.99,))

    def loader(path):
        nonlocal attempts
        with attempts_lock:
            attempts += 1
            attempt = attempts
        if attempt == 1:
            raise failure
        return Model()

    runtime = PhoneticConverter(tmp_path / "lid.ftz", fasttext_loader=loader)
    workers = 16
    start = threading.Barrier(workers + 1)

    def detect():
        start.wait()
        try:
            runtime.detect_language("bonjour")
        except RuntimeError as exc:
            return exc
        return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(detect) for _ in range(workers)]
        start.wait()
        results = [future.result(timeout=2) for future in futures]

    assert attempts == 1
    assert all(result is failure for result in results)

    with pytest.raises(RuntimeError) as repeated:
        runtime.detect_language("again")
    assert repeated.value is failure
    assert attempts == 1

    fresh_runtime = PhoneticConverter(
        tmp_path / "lid.ftz", fasttext_loader=loader
    )
    assert fresh_runtime.detect_language("bonjour") == "__label__en"
    assert attempts == 2


def test_kakasi_initialization_failure_is_shared_by_waiters(tmp_path):
    """Every waiter sees one cached provider failure."""

    attempts = 0
    attempts_lock = threading.Lock()
    failure = RuntimeError("fixture kakasi initialization failed")

    def factory():
        nonlocal attempts
        with attempts_lock:
            attempts += 1
        raise failure

    runtime = PhoneticConverter(tmp_path / "lid.ftz", kakasi_factory=factory)
    workers = 8
    start = threading.Barrier(workers + 1)

    def initialize():
        start.wait()
        try:
            runtime._kakasi_provider()
        except RuntimeError as exc:
            return exc
        return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(initialize) for _ in range(workers)]
        start.wait()
        results = [future.result(timeout=2) for future in futures]

    assert attempts == 1
    assert all(result is failure for result in results)


class _ForwardProbe:
    def __init__(self):
        self.guard = threading.Lock()
        self.first_entered = threading.Event()
        self.second_entered = threading.Event()
        self.release = threading.Event()
        self.active = 0
        self.max_active = 0

    def __call__(self, features):
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active == 1:
                self.first_entered.set()
            elif self.active == 2:
                self.second_entered.set()
        assert self.release.wait(timeout=2), "test did not release fake forward"
        with self.guard:
            self.active -= 1
        return torch.zeros((1, 3, 41), dtype=torch.float32)


def _fake_inference(probe):
    runtime = legacy.LegacyV1Inference(
        asset_root=REPOSITORY_ROOT,
        profile=legacy.load_legacy_v1_profile(),
        device="cpu",
    )
    runtime.extract_features = lambda audio: torch.zeros((1, 1, 128, 9))
    runtime.load_model = lambda logical_name: probe
    return runtime


def test_conc_002_same_runtime_serializes_but_distinct_runtimes_overlap():
    """CONC-002: same-runtime max_active=1; distinct runtimes reach 2."""

    same_probe = _ForwardProbe()
    same_runtime = _fake_inference(same_probe)
    second_started = threading.Event()

    def second_same_runtime():
        second_started.set()
        return same_runtime.predict(torch.zeros(16), acoustic_model="Baseline")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            same_runtime.predict, torch.zeros(16), acoustic_model="Baseline"
        )
        assert same_probe.first_entered.wait(timeout=1)
        second = pool.submit(second_same_runtime)
        assert second_started.wait(timeout=1)
        assert not same_probe.second_entered.wait(timeout=0.05)
        same_probe.release.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert same_probe.max_active == 1

    distinct_probe = _ForwardProbe()
    first_runtime = _fake_inference(distinct_probe)
    second_runtime = _fake_inference(distinct_probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            first_runtime.predict, torch.zeros(16), acoustic_model="Baseline"
        )
        assert distinct_probe.first_entered.wait(timeout=1)
        second = pool.submit(
            second_runtime.predict, torch.zeros(16), acoustic_model="Baseline"
        )
        assert distinct_probe.second_entered.wait(timeout=1)
        distinct_probe.release.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert distinct_probe.max_active == 2


class _ShapedModel(torch.nn.Module):
    def __init__(self, output_classes):
        super().__init__()
        self.output_classes = tuple(output_classes)

    def forward(self, features):
        frames = 3
        shape = (1, frames, *self.output_classes)
        if self.output_classes == (1,):
            return torch.ones(shape, dtype=torch.float32)
        raw = torch.full(shape, -30.0, dtype=torch.float32)
        raw[:, :, 0, ...] = 0.0
        return raw


def test_conc_001_four_routes_initialize_each_runtime_resource_once(monkeypatch):
    """CONC-001: 16 simultaneous mixed-route calls initialize each resource once."""

    load_counts = {"Baseline": 0, "MTL": 0, "BDR": 0}
    create_counts = {(41,): 0, (41, 47): 0, (1,): 0}
    count_lock = threading.Lock()

    def load_state(_path, spec):
        with count_lock:
            load_counts[spec.logical_name] += 1
        return {}

    def create_model(architecture):
        output_classes = tuple(architecture.output_classes)
        with count_lock:
            create_counts[output_classes] += 1
        return _ShapedModel(output_classes)

    monkeypatch.setattr(legacy, "load_checkpoint_state", load_state)
    monkeypatch.setattr(legacy, "_create_model", create_model)
    monkeypatch.setattr(legacy, "strict_load_model_state", lambda *args, **kwargs: None)

    runtime = legacy.LegacyV1Inference(
        asset_locator=_Locator(), profile=legacy.load_legacy_v1_profile()
    )
    monkeypatch.setattr(
        runtime,
        "extract_features",
        lambda _audio: torch.zeros((1, 1, 128, 9), dtype=torch.float32),
    )
    routes = ("Baseline", "MTL", "Baseline_BDR", "MTL_BDR") * 4
    start = threading.Barrier(len(routes) + 1)

    def predict(route):
        start.wait()
        posterior, boundary = runtime.predict(
            torch.zeros(16), acoustic_model=route, seed=11
        )
        return route, posterior, boundary

    with ThreadPoolExecutor(max_workers=len(routes)) as pool:
        futures = [pool.submit(predict, route) for route in routes]
        start.wait()
        results = [future.result(timeout=5) for future in futures]

    assert load_counts == {"Baseline": 1, "MTL": 1, "BDR": 1}
    assert create_counts == {(41,): 1, (41, 47): 1, (1,): 1}
    for route in set(routes):
        matching = [item for item in results if item[0] == route]
        first_posterior, first_boundary = matching[0][1:]
        for _, posterior, boundary in matching[1:]:
            assert torch.equal(posterior, first_posterior)
            if first_boundary is None:
                assert boundary is None
            else:
                assert torch.equal(boundary, first_boundary)


def _numpy_rng_snapshot():
    algorithm, state, position, has_gaussian, cached_gaussian = np.random.get_state()
    return (
        algorithm,
        state.tobytes(),
        position,
        has_gaussian,
        cached_gaussian,
    )


def _smoothed_posterior(raw, seed):
    posterior = F.log_softmax(raw, dim=2).reshape(-1, 41)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    noise = torch.rand(
        posterior.shape,
        dtype=posterior.dtype,
        device=posterior.device,
        generator=generator,
    )
    return torch.log(torch.exp(posterior) + noise * (1e-10 - 1e-11) + 1e-11)


def test_conc_004_interleaved_seeds_are_local_and_preserve_global_rng(monkeypatch):
    """CONC-004: interleaved seeds affect only smoothing and preserve global RNG."""

    runtime = legacy.LegacyV1Inference(
        asset_root=REPOSITORY_ROOT,
        profile=legacy.load_legacy_v1_profile(),
        device="cpu",
    )
    raw = torch.full((1, 3, 41), -30.0, dtype=torch.float32)
    raw[:, :, 0] = 0.0

    class DeterministicAcoustic(torch.nn.Module):
        def forward(self, features):
            assert torch.equal(
                features, torch.zeros((1, 1, 128, 9), dtype=torch.float32)
            )
            return raw.clone()

    runtime._models["Baseline"] = DeterministicAcoustic()
    monkeypatch.setattr(
        runtime,
        "extract_features",
        lambda _audio: torch.zeros((1, 1, 128, 9), dtype=torch.float32),
    )
    seeds = (0, 1, 1, 0, 0, 1, 1, 0)
    start = threading.Barrier(len(seeds) + 1)
    np.random.seed(404)
    torch.manual_seed(404)
    numpy_before = _numpy_rng_snapshot()
    torch_before = torch.random.get_rng_state().clone()

    def predict(seed):
        start.wait()
        posterior, boundary = runtime.predict(
            torch.zeros(16), acoustic_model="Baseline", seed=seed
        )
        assert boundary is None
        return seed, posterior

    with ThreadPoolExecutor(max_workers=len(seeds)) as pool:
        futures = [pool.submit(predict, seed) for seed in seeds]
        start.wait()
        results = [future.result(timeout=5) for future in futures]

    assert _numpy_rng_snapshot() == numpy_before
    assert torch.equal(torch.random.get_rng_state(), torch_before)
    expected = {seed: _smoothed_posterior(raw, seed) for seed in set(seeds)}
    by_seed = {
        seed: [posterior for result_seed, posterior in results if result_seed == seed]
        for seed in set(seeds)
    }
    for posteriors in by_seed.values():
        assert all(torch.equal(posteriors[0], item) for item in posteriors[1:])
    for seed, posterior in results:
        torch.testing.assert_close(posterior, expected[seed], rtol=1e-6, atol=1e-7)
    assert not torch.equal(expected[0], expected[1])


def test_conc_005_sigint_interrupts_lock_wait_without_poisoning_runtime():
    """CONC-005: SIGINT releases a lock waiter and leaves no partial cache."""

    program = textwrap.dedent(
        """
        import os
        import signal
        import threading
        from pathlib import Path

        import torch

        from t2l.adapters import legacy_v1_inference as legacy


        class Locator:
            class Resolved:
                path = Path("validated-checkpoint")

            def resolve(self, _spec):
                return self.Resolved()


        class EmptyModel(torch.nn.Module):
            def forward(self, value):
                return value


        waiter_entered = threading.Event()


        class ObservedRLock:
            def __init__(self):
                self.inner = threading.RLock()

            def __enter__(self):
                if threading.current_thread() is threading.main_thread():
                    waiter_entered.set()
                return self.inner.__enter__()

            def __exit__(self, *exc):
                return self.inner.__exit__(*exc)


        legacy.load_checkpoint_state = lambda _path, _spec: {}
        legacy._create_model = lambda _architecture: EmptyModel()
        legacy.strict_load_model_state = lambda *_args, **_kwargs: None
        runtime = legacy.LegacyV1Inference(
            asset_locator=Locator(), profile=legacy.load_legacy_v1_profile()
        )
        runtime._lock = ObservedRLock()
        holder_entered = threading.Event()
        release_holder = threading.Event()


        def hold_lock():
            with runtime._lock:
                holder_entered.set()
                assert release_holder.wait(timeout=5)


        holder = threading.Thread(target=hold_lock)
        holder.start()
        assert holder_entered.wait(timeout=5)


        def interrupt_waiter():
            assert waiter_entered.wait(timeout=5)
            os.kill(os.getpid(), signal.SIGINT)


        interrupter = threading.Thread(target=interrupt_waiter)
        interrupter.start()
        interrupted = False
        try:
            runtime.load_model("Baseline")
        except KeyboardInterrupt:
            interrupted = True
        finally:
            release_holder.set()
        holder.join(timeout=5)
        interrupter.join(timeout=5)
        assert interrupted
        assert not holder.is_alive()
        assert not interrupter.is_alive()
        assert runtime._models == {}
        assert runtime._model_failures == {}
        assert isinstance(runtime.load_model("Baseline"), EmptyModel)
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT)},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


class _CallProbe:
    def __init__(self):
        self.guard = threading.Lock()
        self.first_entered = threading.Event()
        self.second_entered = threading.Event()
        self.release = threading.Event()
        self.active = 0
        self.max_active = 0

    def enter(self):
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active == 1:
                self.first_entered.set()
            elif self.active == 2:
                self.second_entered.set()
        assert self.release.wait(timeout=5)
        with self.guard:
            self.active -= 1


class _ObservedRLock:
    """Expose a thread's outermost acquire attempt without changing lock semantics."""

    def __init__(self):
        self._inner = threading.RLock()
        self._guard = threading.Lock()
        self._depth_by_thread = {}
        self._outer_attempts = 0
        self.second_outer_attempted = threading.Event()

    def __enter__(self):
        thread_id = threading.get_ident()
        with self._guard:
            if self._depth_by_thread.get(thread_id, 0) == 0:
                self._outer_attempts += 1
                if self._outer_attempts == 2:
                    self.second_outer_attempted.set()
        self._inner.acquire()
        with self._guard:
            self._depth_by_thread[thread_id] = (
                self._depth_by_thread.get(thread_id, 0) + 1
            )
        return self

    def __exit__(self, *_exc):
        thread_id = threading.get_ident()
        with self._guard:
            depth = self._depth_by_thread[thread_id] - 1
            if depth:
                self._depth_by_thread[thread_id] = depth
            else:
                del self._depth_by_thread[thread_id]
        self._inner.release()


def _exercise_same_and_distinct_runtime_calls(call_factory):
    same_probe = _CallProbe()
    same_call, same_owner = call_factory(same_probe)
    observed_lock = _ObservedRLock()
    same_owner._lock = observed_lock

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(same_call)
        assert same_probe.first_entered.wait(timeout=2)
        second = pool.submit(same_call)
        assert observed_lock.second_outer_attempted.wait(timeout=2)
        assert not same_probe.second_entered.is_set()
        same_probe.release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert same_probe.max_active == 1

    distinct_probe = _CallProbe()
    first_call, _first_owner = call_factory(distinct_probe)
    second_call, _second_owner = call_factory(distinct_probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_call)
        assert distinct_probe.first_entered.wait(timeout=2)
        second = pool.submit(second_call)
        assert distinct_probe.second_entered.wait(timeout=2)
        distinct_probe.release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert distinct_probe.max_active == 2


def test_fasttext_calls_are_serial_per_runtime_and_isolated_between_runtimes(tmp_path):
    class Model:
        def __init__(self, probe):
            self.probe = probe

        def predict(self, _text, *, k):
            assert k == 1
            self.probe.enter()
            return (('__label__en',), (1.0,))

    def call_factory(probe):
        converter = PhoneticConverter(
            tmp_path / "lid.ftz", fasttext_loader=lambda _path: Model(probe)
        )
        return (lambda: converter.detect_language("bonjour")), converter

    _exercise_same_and_distinct_runtime_calls(call_factory)


def test_kakasi_calls_are_serial_per_runtime_and_isolated_between_runtimes(tmp_path):
    class Kakasi:
        def __init__(self, probe):
            self.probe = probe

        def convert(self, _text):
            self.probe.enter()
            return ({"orig": "かな", "hepburn": "kana"},)

    def call_factory(probe):
        converter = PhoneticConverter(
            tmp_path / "lid.ftz", kakasi_factory=lambda: Kakasi(probe)
        )
        return (lambda: converter.phonetize("かな")), converter

    _exercise_same_and_distinct_runtime_calls(call_factory)


def test_g2p_calls_are_serial_per_runtime_and_isolated_between_runtimes(tmp_path):
    def call_factory(probe):
        provider = OfflineG2PProvider(
            prepare_resources=lambda: tmp_path,
            resource_finder=lambda _name: True,
            g2p_factory=lambda: lambda text: probe.enter() or (text,),
        )
        return (lambda: provider("hello")), provider

    _exercise_same_and_distinct_runtime_calls(call_factory)


def test_g2p_interrupt_cleans_private_assets_without_caching_control_flow(tmp_path):
    attempts = 0
    snapshots = []

    def prepare_resources():
        owner = tempfile.TemporaryDirectory(dir=tmp_path)
        snapshot = MaterializedAssetSet(owner, {})
        snapshots.append(snapshot)
        return snapshot

    def create_g2p():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise KeyboardInterrupt
        return lambda text: (text.upper(),)

    provider = OfflineG2PProvider(
        prepare_resources=prepare_resources,
        resource_finder=lambda _name: True,
        g2p_factory=create_g2p,
    )

    with pytest.raises(KeyboardInterrupt):
        provider("first")

    assert not snapshots[0].root.exists()
    assert provider._resource_assets is None
    assert provider._failure is None
    assert provider("second") == ("SECOND",)
    assert attempts == 2
    snapshots[1].close()
