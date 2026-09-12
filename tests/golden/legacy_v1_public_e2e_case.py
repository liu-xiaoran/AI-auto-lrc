"""Canonical real-decoder -> public API/installed CLI LegacyV1 case."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

import soundfile
import torch
import torchaudio
from legacy_v1_feature_case import (
    CANONICAL_BASE_IMAGE,
    PINNED_CPU_WHEELS,
    PINNED_PACKAGES,
    REPOSITORY_ROOT,
    SEED,
    environment_mismatches,
    raw_float32_sha256,
    sha256_file,
)

import t2l
from t2l.adapters.audio import AudioPreparationAdapter
from t2l.adapters.legacy_v1_inference import LegacyV1Inference
from t2l.adapters.lyrics import LegacyV1LyricsAdapter
from t2l.model_profiles import load_legacy_v1_profile

ORACLE_PATH = Path(__file__).with_name("legacy_v1_public_e2e_manifest.json")
FIXTURE_METADATA_PATH = (
    REPOSITORY_ROOT / "tests/fixtures/audio/sine-440hz-250ms-mono-22050.json"
)
ROUTES = ("Baseline", "MTL", "Baseline_BDR", "MTL_BDR")
LYRICS = ("a",)


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _diagnostic_record(diagnostic: object) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "stage": diagnostic.stage,
        "message": diagnostic.message,
        "details": dict(diagnostic.details),
    }


def _result_record(result: object) -> dict[str, Any]:
    return {
        "lrc": result.lrc,
        "lrc_sha256": _text_sha256(result.lrc),
        "status": result.status,
        "spans": [
            {
                "token_index": alignment.token_index,
                "line_index": alignment.line_index,
                "text": alignment.text,
                "frame_span": [
                    alignment.frame_span.start,
                    alignment.frame_span.end,
                ],
            }
            for alignment in result.spans
        ],
        "diagnostics": [
            _diagnostic_record(diagnostic) for diagnostic in result.diagnostics
        ],
        "model_profile": result.model_profile,
        "timebase": {
            "sample_rate": result.timebase.sample_rate,
            "hop_length": result.timebase.hop_length,
            "time_pooling": result.timebase.time_pooling,
            "frame_offset": result.timebase.frame_offset,
        },
        "expected_token_count": result.expected_token_count,
        "aligned_token_count": result.aligned_token_count,
    }


def _plan_record(plan: object) -> dict[str, Any]:
    payload = plan.payload
    return {
        "tokens": [
            {
                "token_index": token.token_index,
                "line_index": token.line_index,
                "text": token.text,
            }
            for token in plan.tokens
        ],
        "phones": list(payload.phones),
        "word_spans": [list(span) for span in payload.word_spans],
        "line_spans": [list(span) for span in payload.line_spans],
        "lines": [list(line) for line in payload.lines],
        "phonetics": [list(line) for line in payload.phonetics],
        "pre_lines_unprocessed": payload.pre_lines_unprocessed,
        "diagnostics": [
            _diagnostic_record(diagnostic) for diagnostic in plan.diagnostics
        ],
    }


def _audio_record(audio: object) -> dict[str, Any]:
    samples = audio.samples.detach().cpu().contiguous()
    return {
        "sample_rate": audio.sample_rate,
        "shape": list(samples.shape),
        "dtype": str(samples.numpy().dtype),
        "layout": "C-contiguous little-endian float32 raw bytes",
        "finite": bool(torch.isfinite(samples).all()),
        "raw_little_endian_f32_sha256": raw_float32_sha256(samples),
        "metadata": dict(audio.metadata),
    }


def _tensor_record(value: torch.Tensor) -> dict[str, Any]:
    tensor = value.detach().cpu().contiguous()
    return {
        "shape": list(tensor.shape),
        "dtype": str(tensor.numpy().dtype),
        "layout": "C-contiguous little-endian float32 raw bytes",
        "finite": bool(torch.isfinite(tensor).all()),
        "raw_little_endian_f32_sha256": raw_float32_sha256(tensor),
    }


def _run_public_api(
    route: str,
    fixture_path: Path,
    *,
    timestamp_mode: str = "line",
) -> dict[str, Any]:
    """Call only public API entry points while wrapping real adapters as spies."""

    trace: dict[str, object] = {}
    original_lyrics_prepare = LegacyV1LyricsAdapter.prepare
    original_audio_prepare = AudioPreparationAdapter.prepare
    original_extract_features = LegacyV1Inference.extract_features
    original_predict = LegacyV1Inference.predict

    def traced_lyrics_prepare(adapter, lyrics):
        plan = original_lyrics_prepare(adapter, lyrics)
        trace["plan"] = plan
        return plan

    def traced_audio_prepare(adapter, audio_path, *, vocal_separation, decoder):
        audio = original_audio_prepare(
            adapter,
            audio_path,
            vocal_separation=vocal_separation,
            decoder=decoder,
        )
        trace["audio"] = audio
        return audio

    def traced_extract_features(adapter, audio):
        features = original_extract_features(adapter, audio)
        trace["features"] = features.detach().cpu().clone()
        return features

    def traced_predict(adapter, audio, *, acoustic_model="MTL", seed=0):
        posterior, boundary = original_predict(
            adapter,
            audio,
            acoustic_model=acoustic_model,
            seed=seed,
        )
        trace["predict_route"] = acoustic_model
        trace["posterior"] = posterior.detach().cpu().clone()
        trace["boundary"] = (
            None if boundary is None else boundary.detach().cpu().clone()
        )
        return posterior, boundary

    config = t2l.RuntimeConfig(
        asset_root=REPOSITORY_ROOT,
        device="cpu",
        offline=True,
        decoder="torchaudio",
        seed=SEED,
    )
    runtime = t2l.create_runtime(config)
    request = t2l.AlignmentRequest(
        lyrics=LYRICS,
        audio_path=fixture_path,
        timestamp_mode=timestamp_mode,
        acoustic_model=route,
        allow_partial=False,
        vocal_separation=None,
    )
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(LegacyV1LyricsAdapter, "prepare", traced_lyrics_prepare)
        )
        stack.enter_context(
            patch.object(AudioPreparationAdapter, "prepare", traced_audio_prepare)
        )
        stack.enter_context(
            patch.object(LegacyV1Inference, "extract_features", traced_extract_features)
        )
        stack.enter_context(patch.object(LegacyV1Inference, "predict", traced_predict))
        result = t2l.process(request, runtime=runtime)

    required = {"plan", "audio", "features", "predict_route", "posterior", "boundary"}
    if trace.keys() != required:
        raise RuntimeError(f"public API trace differs: {sorted(trace)}")
    if trace["predict_route"] != route:
        raise RuntimeError(f"public API selected {trace['predict_route']!r}, expected {route!r}")
    if result.status != "complete":
        raise RuntimeError(f"public API route {route} returned {result.status!r}")

    boundary = trace["boundary"]
    return {
        "entry_point": "t2l.process(request, runtime=t2l.create_runtime(config))",
        "request": {
            "lyrics": list(LYRICS),
            "audio_path": "tests/fixtures/audio/sine-440hz-250ms-mono-22050.mp3",
            "timestamp_mode": timestamp_mode,
            "acoustic_model": route,
            "allow_partial": False,
            "vocal_separation": None,
        },
        "config": {
            "asset_root": "/workspace",
            "device": "cpu",
            "offline": True,
            "decoder": "torchaudio",
            "seed": SEED,
        },
        "lyrics_plan": _plan_record(trace["plan"]),
        "decoded_audio": _audio_record(trace["audio"]),
        "features": _tensor_record(trace["features"]),
        "posterior": _tensor_record(trace["posterior"]),
        "boundary": None if boundary is None else _tensor_record(boundary),
        "result": _result_record(result),
    }


def _network_guard_source(marker: Path, import_marker: Path) -> str:
    return (
        "import atexit, pathlib, socket, sys\n"
        f"_marker = pathlib.Path({str(marker)!r})\n"
        f"_import_marker = pathlib.Path({str(import_marker)!r})\n"
        "def _deny(*args, **kwargs):\n"
        "    _marker.write_text('network attempted', encoding='utf-8')\n"
        "    raise AssertionError('network access is forbidden in canonical golden')\n"
        "def _audit_import():\n"
        "    module = sys.modules.get('t2l')\n"
        "    origin = '<missing>' if module is None else str(pathlib.Path(module.__file__).resolve())\n"
        "    _import_marker.write_text(origin, encoding='utf-8')\n"
        "socket.socket.connect = _deny\n"
        "socket.create_connection = _deny\n"
        "atexit.register(_audit_import)\n"
    )


def _run_installed_cli(
    route: str,
    fixture_path: Path,
    *,
    cwd: Path,
    work_root: Path,
    timestamp_mode: str = "line",
) -> dict[str, Any]:
    work_root.mkdir(parents=True, exist_ok=True)
    executable_path = (REPOSITORY_ROOT / ".venv/bin/ai-auto-lrc").resolve()
    if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
        raise RuntimeError("canonical image does not contain the installed console script")
    repository_venv = (REPOSITORY_ROOT / ".venv").resolve()
    if repository_venv not in executable_path.parents:
        raise RuntimeError(f"unexpected console script location: {executable_path}")

    lyrics_path = work_root / "lyrics.txt"
    lyrics_path.write_bytes(b"a\n")
    guard_root = work_root / "network-guard"
    guard_root.mkdir(exist_ok=True)
    marker = work_root / "network-attempted"
    import_marker = work_root / "t2l-import-origin"
    (guard_root / "sitecustomize.py").write_text(
        _network_guard_source(marker, import_marker), encoding="utf-8"
    )
    empty_home = work_root / "empty-home"
    empty_home.mkdir(exist_ok=True)

    command = [
        str(executable_path),
        str(lyrics_path),
        str(fixture_path),
        "--asset-root",
        str(REPOSITORY_ROOT),
        "--device",
        "cpu",
        "--decoder",
        "torchaudio",
        "--acoustic-model",
        route,
        "--timestamps",
        timestamp_mode,
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(empty_home),
            "PYTHONPATH": str(guard_root),
            "PYTHONWARNINGS": "ignore",
            "TORCH_CPP_LOG_LEVEL": "ERROR",
            "XDG_CACHE_HOME": str(empty_home / "cache"),
            "XDG_CONFIG_HOME": str(empty_home / "config"),
            "XDG_DATA_HOME": str(empty_home / "data"),
        }
    )
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if marker.exists():
        raise RuntimeError("installed CLI attempted network access")
    if not import_marker.is_file():
        raise RuntimeError("installed CLI did not report its t2l import origin")
    import_origin = Path(import_marker.read_text(encoding="utf-8")).resolve()
    source_package = (REPOSITORY_ROOT / "t2l").resolve()
    if (
        repository_venv not in import_origin.parents
        or "site-packages" not in import_origin.parts
        or source_package in import_origin.parents
    ):
        raise RuntimeError(
            f"installed CLI imported t2l from a non-installed origin: {import_origin}"
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"installed CLI route {route} failed with {completed.returncode}: "
            f"{completed.stderr.decode('utf-8', errors='replace')}"
        )
    if completed.stderr != b"":
        raise RuntimeError(f"installed CLI route {route} wrote unexpected stderr")
    stdout = completed.stdout.decode("utf-8")
    return {
        "entry_point": "installed ai-auto-lrc console script",
        "command": [
            "ai-auto-lrc",
            "<lyrics.txt>",
            "<fixture.mp3>",
            "--asset-root",
            "<repository-root>",
            "--device",
            "cpu",
            "--decoder",
            "torchaudio",
            "--acoustic-model",
            route,
            "--timestamps",
            timestamp_mode,
        ],
        "working_directory": (
            "repository-root" if cwd == REPOSITORY_ROOT else "outside-repository"
        ),
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stdout_sha256": _text_sha256(stdout),
        "stderr": "",
        "stderr_sha256": _text_sha256(""),
        "network_attempted": False,
        "t2l_import_origin": str(import_origin),
        "t2l_imported_from_installed_site_packages": True,
    }


def _distribution_record() -> dict[str, Any]:
    distribution = importlib.metadata.distribution("ai-auto-lrc")
    entry_points = {
        entry.name: entry.value
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }
    return {
        "name": distribution.metadata["Name"],
        "version": distribution.version,
        "console_entry_point": entry_points.get("ai-auto-lrc"),
    }


def build_public_e2e_candidate() -> dict[str, Any]:
    torch.set_num_threads(1)
    mismatches = environment_mismatches()
    if mismatches:
        raise RuntimeError("non-canonical environment: " + "; ".join(mismatches))

    available_backends = torchaudio.list_audio_backends()
    if available_backends != ["soundfile"]:
        raise RuntimeError(
            f"canonical decoder backends differ: {available_backends!r}, "
            "expected ['soundfile']"
        )

    fixture_metadata = json.loads(FIXTURE_METADATA_PATH.read_text(encoding="utf-8"))
    fixture_path = FIXTURE_METADATA_PATH.with_name(fixture_metadata["file"])
    fixture_bytes = fixture_path.read_bytes()
    if len(fixture_bytes) != fixture_metadata["size_bytes"]:
        raise RuntimeError("audio fixture size differs from its metadata")
    if hashlib.sha256(fixture_bytes).hexdigest() != fixture_metadata["sha256"]:
        raise RuntimeError("audio fixture hash differs from its metadata")

    demucs_modules_before = sorted(
        name for name in sys.modules if name == "demucs" or name.startswith("demucs.")
    )
    if demucs_modules_before:
        raise RuntimeError("Demucs was imported before the default public API run")

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def deny_network(*args, **kwargs):
        raise AssertionError("network access is forbidden in canonical golden")

    with (
        patch.object(socket.socket, "connect", deny_network),
        patch.object(socket, "create_connection", deny_network),
    ):
        api_records = {
            route: _run_public_api(route, fixture_path) for route in ROUTES
        }
        baseline_bdr_word_api = _run_public_api(
            "Baseline_BDR",
            fixture_path,
            timestamp_mode="word",
        )
    if socket.socket.connect is not original_connect:
        raise RuntimeError("socket.connect was not restored after public API run")
    if socket.create_connection is not original_create_connection:
        raise RuntimeError("socket.create_connection was not restored after public API run")

    demucs_modules_after = sorted(
        name for name in sys.modules if name == "demucs" or name.startswith("demucs.")
    )
    if demucs_modules_after:
        raise RuntimeError("default public API imported Demucs")

    with tempfile.TemporaryDirectory(prefix="t2l-public-golden-", dir="/tmp") as temp:
        work_root = Path(temp)
        outside_cwd = work_root / "outside-repository"
        outside_cwd.mkdir()
        cli_records = {
            route: _run_installed_cli(
                route,
                fixture_path,
                cwd=outside_cwd,
                work_root=work_root / route,
            )
            for route in ROUTES
        }
        baseline_bdr_word_cli = _run_installed_cli(
            "Baseline_BDR",
            fixture_path,
            cwd=outside_cwd,
            work_root=work_root / "Baseline_BDR-word",
            timestamp_mode="word",
        )
        root_cli_record = _run_installed_cli(
            "MTL",
            fixture_path,
            cwd=REPOSITORY_ROOT,
            work_root=work_root / "MTL-repository-root",
        )

    for route in ROUTES:
        api_lrc = api_records[route]["result"]["lrc"]
        expected_stdout = f"{api_lrc}\n"
        if cli_records[route]["stdout"] != expected_stdout:
            raise RuntimeError(f"{route} API and installed CLI output differ")
    if baseline_bdr_word_cli["stdout"] != f"{baseline_bdr_word_api['result']['lrc']}\n":
        raise RuntimeError("Baseline_BDR word API and installed CLI output differ")
    if root_cli_record["stdout"] != cli_records["MTL"]["stdout"]:
        raise RuntimeError("installed CLI output depends on the current working directory")

    profile = load_legacy_v1_profile()
    route_records: dict[str, Any] = {}
    for route in ROUTES:
        model_name = route.removesuffix("_BDR")
        with_boundary = route.endswith("_BDR")
        route_record = {
            "model_name": model_name,
            "architecture_id": profile.checkpoints[model_name].architecture_id,
            "checkpoint_sha256": profile.checkpoints[model_name].sha256,
            "boundary_checkpoint_sha256": (
                profile.checkpoints["BDR"].sha256 if with_boundary else None
            ),
            "python_api": api_records[route],
            "installed_cli": cli_records[route],
        }
        if route == "Baseline_BDR":
            route_record.update(
                {
                    "python_api_word": baseline_bdr_word_api,
                    "installed_cli_word": baseline_bdr_word_cli,
                }
            )
        route_records[route] = route_record

    return {
        "schema_version": 1,
        "status": "canonical",
        "case_id": "GOL-001-GOL-002-GOL-003-GOL-007-GOL-008-GOL-011-GOL-012-public-e2e",
        "oracle_id": "legacy-v1-real-mp3-public-api-installed-cli-linux-x86_64-cpython310",
        "scope": "real-decoder-public-api-installed-cli",
        "generated_from_commit": "db8e714eceb73e88496f0f705a56cd8c571e0278",
        "environment": {
            "base_image": CANONICAL_BASE_IMAGE,
            "system": "Linux",
            "machine": "x86_64",
            "python_version": "3.10.21",
            "packages": {
                **PINNED_PACKAGES,
                "soundfile": importlib.metadata.version("soundfile"),
            },
            "cpu_wheels": PINNED_CPU_WHEELS,
            "device": "cpu",
            "torch_cuda_version": None,
            "torch_intraop_threads": 1,
            "omp_num_threads": "1",
            "mkl_num_threads": "1",
            "network": "docker --network none plus socket denial guards",
            "cli_torch_cpp_log_level": "ERROR",
        },
        "provenance": {
            "provenance_scope": "canonical functional evidence; not clean release provenance",
            "candidate_worktree_state": "dirty",
            "candidate_source_sha256": sha256_file(Path(__file__)),
            "api_source_sha256": sha256_file(REPOSITORY_ROOT / "t2l/api.py"),
            "composition_source_sha256": sha256_file(
                REPOSITORY_ROOT / "t2l/composition.py"
            ),
            "audio_adapter_sha256": sha256_file(
                REPOSITORY_ROOT / "t2l/adapters/audio.py"
            ),
            "lyrics_adapter_sha256": sha256_file(
                REPOSITORY_ROOT / "t2l/adapters/lyrics.py"
            ),
            "inference_adapter_sha256": sha256_file(
                REPOSITORY_ROOT / "t2l/adapters/legacy_v1_inference.py"
            ),
            "cli_source_sha256": sha256_file(
                REPOSITORY_ROOT / "t2l/adapters/cli.py"
            ),
            "profile_manifest_sha256": sha256_file(
                REPOSITORY_ROOT / "t2l/_assets/legacy_v1_manifest.json"
            ),
            "uv_lock_sha256": sha256_file(REPOSITORY_ROOT / "uv.lock"),
            "fixture_metadata_sha256": sha256_file(FIXTURE_METADATA_PATH),
        },
        "distribution": _distribution_record(),
        "decoder": {
            "policy": "torchaudio",
            "torchaudio_version": importlib.metadata.version("torchaudio"),
            "dispatcher_available_backends": available_backends,
            "effective_backend": "soundfile (only available dispatcher backend)",
            "soundfile_version": importlib.metadata.version("soundfile"),
            "libsndfile_version": soundfile.__libsndfile_version__,
        },
        "input": {
            "file": "tests/fixtures/audio/sine-440hz-250ms-mono-22050.mp3",
            "encoded_sha256": fixture_metadata["sha256"],
            "encoded_size_bytes": fixture_metadata["size_bytes"],
            "source": fixture_metadata["source"],
            "rights_source": fixture_metadata["rights_source"],
            "allowed_uses": fixture_metadata["allowed_uses"],
            "generator": fixture_metadata["generator"],
            "encoded_audio": fixture_metadata["encoded_audio"],
            "lyrics_utf8": "a\n",
            "lyrics_utf8_sha256": _text_sha256("a\n"),
            "seed": SEED,
            "separation": "none",
            "repeat_count": 3,
        },
        "profile": {
            "profile_id": profile.profile_id,
            "feature_spec_id": profile.feature.spec_id,
            "phone_inventory_id": profile.phone_inventory_id,
            "frame_clock": [
                profile.frame_clock_numerator,
                profile.frame_clock_denominator,
            ],
        },
        "demucs": {
            "requested": False,
            "modules_before": demucs_modules_before,
            "modules_after": demucs_modules_after,
        },
        "cwd_independence": {
            "route": "MTL",
            "repository_root_stdout_sha256": root_cli_record["stdout_sha256"],
            "outside_repository_stdout_sha256": cli_records["MTL"]["stdout_sha256"],
            "exactly_equal": True,
        },
        "routes": route_records,
    }


def load_public_e2e_oracle() -> dict[str, Any]:
    return json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
