"""Image pipeline package.

Inference modules are imported lazily so API contract tests do not require the
full CUDA runtime.
"""

__all__ = ["PipelineRuntime", "get_default_runtime", "run_pipeline"]


def __getattr__(name):
    if name in __all__:
        from . import pipeline

        return getattr(pipeline, name)
    raise AttributeError(name)
