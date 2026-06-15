"""校验 pyproject.toml 中的 dependencies 与 requirements.txt 是否同步。

使用：python scripts/check_requirements_sync.py
退出码：0 同步，1 不同步。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"


def _normalize(spec: str) -> str:
    """归一化依赖项：去空格、转小写、去注释。"""
    return re.sub(r"\s+", "", spec.split("#", 1)[0]).lower()


def _load_pyproject_deps() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project", {})
    deps: list[str] = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    for extras in optional.values():
        deps.extend(extras)
    return {_normalize(d) for d in deps if d.strip()}


def _load_requirements_deps() -> set[str]:
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    return {
        _normalize(line)
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    }


def main() -> int:
    pyproject_deps = _load_pyproject_deps()
    requirements_deps = _load_requirements_deps()

    only_in_pyproject = pyproject_deps - requirements_deps
    only_in_requirements = requirements_deps - pyproject_deps

    if not only_in_pyproject and not only_in_requirements:
        print("[OK] pyproject.toml 与 requirements.txt 同步")
        return 0

    print("[FAIL] pyproject.toml 与 requirements.txt 不同步")
    if only_in_pyproject:
        print("  仅在 pyproject.toml 中：")
        for dep in sorted(only_in_pyproject):
            print(f"    - {dep}")
    if only_in_requirements:
        print("  仅在 requirements.txt 中：")
        for dep in sorted(only_in_requirements):
            print(f"    - {dep}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
