"""
Node 确定性预检 —— 用 story-review 自带的 node 脚本对成稿做机械校验

脚本（只读，不修改正文）：
- check-ai-patterns.js --check --json --fail-on=blocking   → AI 句式/禁词/退化模式
- normalize-punctuation.js --check                         → 标点问题（省略号/破折号等，纯文本输出）
- check-degeneration.js --check --json                     → 模型退化（复读/截断/占位符）

设计：
- node 或脚本缺失时静默跳过，返回空结果 + reason（不抛异常）
- 输出对齐 story-review 的合并规则：blocking → S2，advisory → S4
- 只报告，不修改正文（去AI味改写交给 Polisher / 审查建议）
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .skill_knowledge import resolve_skills_dir

# (脚本名, 附加参数)；normalize-punctuation 不支持 --json
_SCRIPTS_JSON = (
    ("check-ai-patterns.js", ("--check", "--json", "--fail-on=blocking")),
    ("check-degeneration.js", ("--check", "--json")),
)
_SCRIPT_TEXT = "normalize-punctuation.js"

# 纯文本行：<file>:<line>:<col>: <type>: <message>
_TEXT_LINE_RE = re.compile(r"^(.+?):(\d+):(\d+):\s*([^:]+):\s*(.*)$")

_SEVERITY_MAP = {
    "blocking": "S2",
    "advisory": "S4",
}


def _script_path(skill: str, name: str) -> Path:
    return resolve_skills_dir() / skill / "scripts" / name


def _json_findings(raw: str) -> list[dict]:
    """解析 JSON 输出 {findings:[...]} 或裸数组。"""
    raw = (raw or "").strip()
    if not raw:
        return []
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            data = None
    else:
        data = None
    if data is None:
        return []
    items = data.get("findings") if isinstance(data, dict) else data
    if isinstance(items, list):
        return [d for d in items if isinstance(d, dict)]
    return []


def _collect_json(script_name: str, raw: str, source: str) -> list:
    out = []
    for it in _json_findings(raw):
        sev = _SEVERITY_MAP.get(it.get("severity"), "S4")
        cat = it.get("category") or it.get("type") or script_name
        location = f"{it.get('line', '?')}:{it.get('column', '?')}"
        message = (it.get("message") or it.get("hint") or "").strip()
        if not message:
            continue
        out.append({
            "severity": sev,
            "category": cat,
            "location": location,
            "evidence": (it.get("excerpt") or "").strip(),
            "issue": message,
            "fix": (it.get("fix") or it.get("suggestion") or "").strip(),
            "source": source,
        })
    return out


def _collect_text(raw: str, source: str) -> list:
    out = []
    for line in (raw or "").splitlines():
        m = _TEXT_LINE_RE.match(line.strip())
        if not m:
            continue
        _, lineno, colno, ftype, message = m.groups()
        out.append({
            "severity": "S3",
            "category": "format",
            "location": f"{lineno}:{colno}",
            "evidence": "",
            "issue": message.strip(),
            "fix": "",
            "source": source,
        })
    return out


def run_precheck(text: str, skill: str = "story-review") -> dict:
    """对正文跑全部 node 预检脚本。

    Returns:
        {"ok": bool, "findings": [...], "scripts_run": [...], "reason": str}
        node/脚本缺失时 ok=False 且 reason 说明原因（不抛异常）。
    """
    if not text or not text.strip():
        return {"ok": False, "findings": [], "scripts_run": [], "reason": "empty text"}

    if shutil.which("node") is None:
        return {"ok": False, "findings": [], "scripts_run": [], "reason": "node not found"}

    findings: list[dict] = []
    scripts_run: list[str] = []

    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="precheck_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)

        for script_name, extra_args in _SCRIPTS_JSON:
            path = _script_path(skill, script_name)
            if not path.is_file():
                continue
            try:
                proc = subprocess.run(
                    ["node", str(path), *extra_args, tmp_path],
                    capture_output=True, text=True, timeout=60,
                    encoding="utf-8", errors="replace",
                )
                scripts_run.append(script_name)
                raw = proc.stdout or (proc.stderr if proc.returncode != 0 else "")
                findings.extend(_collect_json(script_name, raw, f"node:{script_name}"))
            except (subprocess.SubprocessError, OSError):
                continue

        text_path = _script_path(skill, _SCRIPT_TEXT)
        if text_path.is_file():
            try:
                proc = subprocess.run(
                    ["node", str(text_path), "--check", tmp_path],
                    capture_output=True, text=True, timeout=60,
                    encoding="utf-8", errors="replace",
                )
                scripts_run.append(_SCRIPT_TEXT)
                raw = proc.stdout or (proc.stderr if proc.returncode != 0 else "")
                findings.extend(_collect_text(raw, f"node:{_SCRIPT_TEXT}"))
            except (subprocess.SubprocessError, OSError):
                pass
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # story-review 合并规则：同一位置的 em-dash 破折号，normalize-punctuation 的
    # 机械替换建议去重丢弃，保留 check-ai-patterns 的语义改写建议，避免互相冲突。
    findings = _dedupe_em_dash(findings)

    return {
        "ok": bool(scripts_run),
        "findings": findings,
        "scripts_run": scripts_run,
        "reason": "" if scripts_run else "precheck scripts not found",
    }


def _dedupe_em_dash(findings: list[dict]) -> list[dict]:
    """同位置 em-dash 去重：保留 check-ai-patterns 的，丢弃 normalize-punctuation 的。"""
    semantic = set()
    for f in findings:
        if f.get("category") == "em-dash" and f.get("source") == "node:check-ai-patterns.js":
            semantic.add(f.get("location"))
    if not semantic:
        return findings
    out = []
    for f in findings:
        if (f.get("category") == "em-dash"
                and f.get("source") == "node:normalize-punctuation.js"
                and f.get("location") in semantic):
            continue
        out.append(f)
    return out