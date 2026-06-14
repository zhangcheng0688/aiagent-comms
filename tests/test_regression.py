"""回归测试：把根目录稳定的 mock-mode 脚本作为 pytest case 跑。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable  # 兼容 CI：GitHub Actions 不一定使用 .venv

# 这些脚本不依赖真实 LLM / 外部服务，可在 CI 中稳定通过
MOCK_SCRIPTS = [
    "test_e2e.py",
    "test_v30_integration.py",
    "test_email_parser.py",
]


@pytest.mark.parametrize("script", MOCK_SCRIPTS)
def test_script_runs_successfully(script: str) -> None:
    """以子进程运行脚本，验证退出码为 0 且输出包含成功标记。"""
    script_path = ROOT / script
    result = subprocess.run(
        [str(PYTHON), str(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"{script} exited {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    success_markers = {
        "test_e2e.py": "✅ 全部测试场景跑完",
        "test_v30_integration.py": "20/20 通过",
        "test_email_parser.py": "✅ ALL PASS",
    }
    marker = success_markers[script]
    assert marker in combined, f"{script} did not emit expected success marker: {marker!r}\n{combined}"
