"""Code metrics without external tooling.

Lexical counts are exact. The complexity number is McCabe-style (1 + decision
points) computed from Python's AST, which is exact for Python. The
maintainability score is a documented heuristic, not a certified index — the UI
labels it as such so nobody mistakes it for a formal audit.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass

GRADE_BANDS = [(85, "A"), (70, "B"), (55, "C"), (40, "D"), (0, "F")]

LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
}


@dataclass
class Counts:
    lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    functions: int = 0
    classes: int = 0
    todos: int = 0


def _language(path: str) -> str:
    lowered = path.lower()
    for suffix, name in LANGUAGES.items():
        if lowered.endswith(suffix):
            return name
    return "Plain text"


def _line_counts(code: str) -> Counts:
    lines = code.splitlines()
    counts = Counts(lines=len(lines))
    for line in lines:
        stripped = line.strip()
        if not stripped:
            counts.blank_lines += 1
        elif stripped.startswith(("#", "//", "/*", "*")):
            counts.comment_lines += 1
        else:
            counts.code_lines += 1
        if "TODO" in line or "FIXME" in line:
            counts.todos += 1
    return counts


class _Complexity(ast.NodeVisitor):
    """Counts decision points and nesting per function."""

    def __init__(self) -> None:
        self.functions: list[tuple[str, int, int]] = []  # name, cc, nesting
        self.classes = 0
        self._stack: list[str] = []


    def _visit_function(self, node) -> None:  # noqa: ANN001
        name = getattr(node, "name", "<lambda>")
        inner = _Complexity()
        for child in ast.iter_child_nodes(node):
            inner.visit(child)
        branching = inner.decision_points + 1
        self.functions.append((name, branching, inner.max_nesting))
        self.functions.extend(inner.functions)
        self.classes += inner.classes

    visit_FunctionDef = _visit_function  # type: ignore[assignment]
    visit_AsyncFunctionDef = _visit_function  # type: ignore[assignment]

    def visit_ClassDef(self, node) -> None:  # noqa: ANN001
        self.classes += 1
        self.generic_visit(node)

    def visit_If(self, node) -> None:  # noqa: ANN001
        self._bump(node)

    def visit_For(self, node) -> None:  # noqa: ANN001
        self._bump(node)

    visit_AsyncFor = visit_For  # type: ignore[assignment]

    def visit_While(self, node) -> None:  # noqa: ANN001
        self._bump(node)

    def visit_ExceptHandler(self, node) -> None:  # noqa: ANN001
        self._bump(node)

    def visit_IfExp(self, node) -> None:  # noqa: ANN001
        self._bump(node)

    def visit_BoolOp(self, node) -> None:  # noqa: ANN001
        self._bump(node)

    def visit_Assert(self, node) -> None:  # noqa: ANN001
        self._bump(node)

    def visit_comprehension(self, node) -> None:  # noqa: ANN001
        self._bump(node)

    def _bump(self, node) -> None:  # noqa: ANN001
        self.decision_points += 1
        self.depth += 1
        self.max_nesting = max(self.max_nesting, self.depth)
        self.generic_visit(node)
        self.depth -= 1

    # attributes initialised lazily to keep the visitor small
    def visit(self, node, *args, **kwargs):  # noqa: ANN001
        if not hasattr(self, "decision_points"):
            self.decision_points = 0
            self.depth = 0
            self.max_nesting = 0
        return super().visit(node, *args, **kwargs)


class _Bottlenecks(ast.NodeVisitor):
    """Flag visible patterns that may grow with input size; this is not a profiler."""

    def __init__(self) -> None:
        self.warnings: list[dict[str, str | int]] = []
        self.loop_depth = 0

    def _visit_loop(self, node) -> None:  # noqa: ANN001
        self.loop_depth += 1
        if self.loop_depth == 2:
            self.warnings.append(
                {
                    "line": node.lineno,
                    "kind": "nested_loops",
                    "message": "Nested loops may scale quadratically; check input sizes and repeated lookups.",
                }
            )
        for child in ast.iter_child_nodes(node):
            self.visit(child)
        self.loop_depth -= 1

    visit_For = _visit_loop  # type: ignore[assignment]
    visit_AsyncFor = _visit_loop  # type: ignore[assignment]
    visit_While = _visit_loop  # type: ignore[assignment]


def _grade(score: int) -> str:
    for threshold, letter in GRADE_BANDS:
        if score >= threshold:
            return letter
    return "F"


def _maintainability(counts: Counts, avg_cc: float, nesting: int, long_functions: int) -> int:
    score = 100.0
    score -= max(0.0, avg_cc - 4) * 3.5
    score -= max(0, nesting - 2) * 4
    if counts.code_lines > 40 and counts.comment_lines / max(counts.code_lines, 1) < 0.08:
        score -= 8
    score -= min(long_functions * 4, 20)
    score -= min(counts.todos, 5)
    return int(max(5, min(100, round(score))))


def analyse_file(path: str, code: str) -> dict:
    counts = _line_counts(code)
    language = _language(path)
    result = {
        "path": path,
        "language": language,
        **asdict(counts),
        "average_complexity": None,
        "max_complexity": None,
        "max_nesting": None,
        "maintainability": None,
        "grade": None,
        "bottleneck_warnings": [],
        "error": None,
    }

    if language != "Python":
        result["error"] = "Complexity is Python-only; line counts are exact."
        return result

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        result["error"] = f"Could not parse: {exc.msg} (line {exc.lineno})"
        return result

    visitor = _Complexity()
    visitor.visit(tree)
    bottlenecks = _Bottlenecks()
    bottlenecks.visit(tree)
    counts.classes = visitor.classes
    counts.functions = len(visitor.functions)
    result["functions"] = counts.functions
    result["classes"] = counts.classes

    complexities = [cc for _, cc, _ in visitor.functions] or [visitor.decision_points + 1]
    nesting = max([depth for _, _, depth in visitor.functions] or [visitor.max_nesting])
    long_functions = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length > 50:
                long_functions += 1

    avg_cc = sum(complexities) / len(complexities)
    score = _maintainability(counts, avg_cc, nesting, long_functions)

    result.update(
        {
            "average_complexity": round(avg_cc, 1),
            "max_complexity": max(complexities),
            "max_nesting": nesting,
            "maintainability": score,
            "grade": _grade(score),
            "bottleneck_warnings": bottlenecks.warnings,
        }
    )
    return result


def analyse(code_by_file: dict[str, str]) -> dict:
    if not code_by_file:
        return {"available": False, "reason": "No code stored for this review.", "files": []}

    files = [analyse_file(path, code) for path, code in sorted(code_by_file.items())]
    python_files = [item for item in files if item["language"] == "Python" and not item["error"]]

    totals = {
        "files": len(files),
        "lines": sum(item["lines"] for item in files),
        "code_lines": sum(item["code_lines"] for item in files),
        "comment_lines": sum(item["comment_lines"] for item in files),
        "functions": sum(item["functions"] or 0 for item in files),
        "classes": sum(item["classes"] or 0 for item in files),
        "todos": sum(item["todos"] for item in files),
    }

    if python_files:
        weights = [max(item["code_lines"], 1) for item in python_files]
        weighted = sum(item["maintainability"] * weight for item, weight in zip(python_files, weights))
        score = int(round(weighted / sum(weights)))
        complexity = {
            "average": round(
                sum(item["average_complexity"] for item in python_files) / len(python_files), 1
            ),
            "max": max(item["max_complexity"] for item in python_files),
            "max_nesting": max(item["max_nesting"] for item in python_files),
        }
        maintainability = {"score": score, "grade": _grade(score), "label": "heuristic"}
    else:
        complexity = {"average": None, "max": None, "max_nesting": None}
        maintainability = {
            "score": None,
            "grade": None,
            "label": "Complexity metrics are only computed for Python files.",
        }

    return {
        "available": True,
        "files": files,
        "totals": totals,
        "complexity": complexity,
        "maintainability": maintainability,
        "bottleneck_warnings": [
            {"path": item["path"], **warning}
            for item in files
            for warning in item.get("bottleneck_warnings", [])
        ],
    }
