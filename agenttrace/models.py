"""Versioned, validated JSON trace format. Durations are in milliseconds."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import math
from typing import Any


class TraceValidationError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise TraceValidationError(message)


def _text(value, name):
    _require(isinstance(value, str) and bool(value.strip()), f"{name} 必须是非空字符串")


def _reject_constant(value):
    raise TraceValidationError(f"JSON 不支持非有限数值：{value}")


def _finite_float(value):
    result = float(value)
    _require(math.isfinite(result), "JSON 数值超出有限浮点数范围")
    return result


@dataclass
class Step:
    id: str
    name: str
    kind: str
    status: str
    started_at: str
    duration_ms: float
    input: Any = None
    output: Any = None
    tool: str | None = None
    error: str | None = None

    def __post_init__(self):
        for key in ("id", "name", "started_at"):
            _text(getattr(self, key), key)
        _require(self.kind in {"agent", "tool", "transform"}, "kind 必须是 agent/tool/transform")
        _require(self.status in {"success", "failed", "skipped"}, "步骤状态无效")
        _require(type(self.duration_ms) in (int, float) and math.isfinite(self.duration_ms) and self.duration_ms >= 0, "耗时必须是有限非负数")
        try:
            datetime.fromisoformat(self.started_at)
        except ValueError as exc:
            raise TraceValidationError("started_at 必须为 ISO 时间") from exc
        _require(self.tool is None or isinstance(self.tool, str), "tool 必须为字符串或 null")
        _require(self.error is None or isinstance(self.error, str), "error 必须为字符串或 null")
        if self.status == "failed":
            _text(self.error, "失败步骤的 error")


@dataclass
class Run:
    id: str
    name: str
    status: str
    started_at: str
    steps: list[Step]
    simulated: bool = True
    metadata: dict = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self):
        for key in ("id", "name", "started_at"):
            _text(getattr(self, key), key)
        try:
            datetime.fromisoformat(self.started_at)
        except ValueError as exc:
            raise TraceValidationError("started_at 必须为 ISO 时间") from exc
        _require(type(self.schema_version) is int and self.schema_version == 1, "仅支持 schema_version=1")
        _require(self.status in {"success", "failed"}, "运行状态无效")
        _require(type(self.simulated) is bool, "simulated 必须为布尔值")
        _require(isinstance(self.metadata, dict), "metadata 必须为对象")
        _require(isinstance(self.steps, list) and all(isinstance(s, Step) for s in self.steps), "steps 必须为步骤列表")
        _require(len({s.id for s in self.steps}) == len(self.steps), "步骤 id 不得重复")
        _require(math.isfinite(self.duration_ms), "累计步骤耗时必须是有限数值")
        _require(self.status != "success" or all(s.status != "failed" for s in self.steps), "成功运行不能包含失败步骤")
        _require(self.status != "failed" or any(s.status == "failed" for s in self.steps), "失败运行必须包含失败步骤")

    @property
    def duration_ms(self):
        """Sequential MVP: sum of recorded step durations, not wall-clock latency."""
        return sum(step.duration_ms for step in self.steps)

    @property
    def success_rate(self):
        executed = [s for s in self.steps if s.status != "skipped"]
        return sum(s.status == "success" for s in executed) / len(executed) if executed else 0.0

    def to_json(self):
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, allow_nan=False)

    @classmethod
    def from_json(cls, content: str | bytes):
        try:
            if isinstance(content, bytes):
                content = content.decode("utf-8-sig")
            data = json.loads(content, parse_constant=_reject_constant, parse_float=_finite_float)
            _require(isinstance(data, dict), "JSON 顶层必须是一个运行对象")
            _require(isinstance(data.get("steps"), list), "缺少 steps 列表")
            data["steps"] = [Step(**s) for s in data["steps"]]
            return cls(**data)
        except TraceValidationError:
            raise
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
            raise TraceValidationError(f"无法解析运行记录：{exc}") from exc
