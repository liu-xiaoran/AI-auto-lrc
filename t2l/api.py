"""Side-effect-free Python entry points for v2 alignment."""

from __future__ import annotations

from dataclasses import dataclass

from .application.align_lyrics import AlignLyricsUseCase
from .application.ports import NullProgressObserver
from .contracts import AlignmentRequest, AlignmentResult, RuntimeConfig
from .errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class AlignmentRuntime:
    """Reusable owner of configured alignment application services."""

    config: RuntimeConfig
    use_case: AlignLyricsUseCase

    def process(self, request: AlignmentRequest) -> AlignmentResult:
        return self.use_case.execute(request, self.config)

    __call__ = process


def create_runtime(config=RuntimeConfig()):
    """Create the default lazily-loaded runtime at the sole composition root."""

    if not isinstance(config, RuntimeConfig):
        raise ConfigurationError("config must be a RuntimeConfig")
    from .composition import create_default_runtime

    return create_default_runtime(
        config,
        progress_observer=NullProgressObserver(),
    )


def process(request, *, runtime=None):
    """Align one request without performing file or console I/O."""

    if not isinstance(request, AlignmentRequest):
        raise ConfigurationError("request must be an AlignmentRequest")
    selected_runtime = create_runtime() if runtime is None else runtime
    return selected_runtime.process(request)


__all__ = ["AlignmentRuntime", "create_runtime", "process"]
