"""Isolated model process: JSON on stdin/stdout, diagnostics on stderr."""
import json
import sys
import traceback

from .contracts import NetworkOutput, RunInput
from .errors import ApiProblem
from .routing import calculate_routes
from .run_artifacts import canonical_bytes
from .parent_lifetime import watch_parent


def main():
    try:
        watch_parent()
        document = json.load(sys.stdin)
        request = RunInput.model_validate(document["request"])
        network = NetworkOutput.model_validate(document["network"])
        baseline, blocked, metrics = calculate_routes(network, request.origin, request.destination, request.blocked_edges)
        output = {"baseline": baseline.model_dump(), "blocked": blocked.model_dump(), "metrics": metrics.model_dump()}
        status = 0
    except ApiProblem as error:
        output = {"error": {"code": error.code, "message": error.message, "detail": error.detail}}
        status = 1
    except Exception:
        traceback.print_exc(file=sys.stderr)
        output = {"error": {"code": "MODEL_ERROR", "message": "模型执行失败", "detail": None}}
        status = 1
    sys.stdout.buffer.write(canonical_bytes(output))
    sys.stdout.buffer.flush()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
