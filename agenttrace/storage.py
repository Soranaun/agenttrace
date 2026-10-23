from pathlib import Path
from .models import Run, TraceValidationError

MAX_TRACE_BYTES = 5 * 1024 * 1024


def load_trace(path):
    path = Path(path)
    if path.stat().st_size > MAX_TRACE_BYTES:
        raise TraceValidationError("记录超过 5 MB 限制")
    return Run.from_json(path.read_bytes())


def load_directory(directory):
    runs, errors = [], []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            runs.append(load_trace(path))
        except (OSError, TraceValidationError) as exc:
            errors.append(f"{path.name}: {exc}")
    return runs, errors
