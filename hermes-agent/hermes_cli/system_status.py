"""Read-only Hermes/Codex/account/network status collection.

This module deliberately keeps secrets out of the returned text. It is used by
``/zhuangtai`` in both the CLI and gateway. Network probes are best-effort:
missing internet access must not make the status command fail completely.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, getproxies, urlopen


@dataclass(frozen=True)
class StatusSnapshot:
    model: str = ""
    provider: str = ""
    codex: dict[str, Any] | None = None
    codex_radar: dict[str, Any] | None = None
    network: dict[str, Any] | None = None


def _fmt_time(epoch: Any) -> str:
    try:
        return datetime.fromtimestamp(float(epoch)).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    except (TypeError, ValueError, OSError, OverflowError):
        return "未知"


def _remaining(used: Any) -> str:
    try:
        return f"剩余 {max(0, 100 - int(used))}%"
    except (TypeError, ValueError):
        return "剩余 未知"


def _safe_proxy(value: str) -> str:
    """Return a proxy URL without userinfo or credentials."""
    try:
        parsed = urlparse(value)
        if not parsed.hostname:
            return "已配置（地址隐藏）"
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port else ""
        scheme = parsed.scheme or "proxy"
        return f"{scheme}://{host}{port}"
    except Exception:
        return "已配置（地址隐藏）"


def _proxy_info() -> str:
    values: list[str] = []
    seen: set[str] = set()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        raw = os.environ.get(key, "").strip()
        if raw:
            item = f"{key.upper()}={_safe_proxy(raw)}"
            if item not in seen:
                seen.add(item)
                values.append(item)
    if values:
        return "; ".join(values)
    try:
        proxies = getproxies()
        for key in ("http", "https", "all"):
            raw = proxies.get(key, "")
            if raw:
                item = f"{key.upper()}={_safe_proxy(raw)}"
                if item not in seen:
                    seen.add(item)
                    values.append(item)
    except Exception:
        pass
    return "; ".join(values) if values else "未检测到"


def _local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "未知"
    finally:
        sock.close()


def _http_get(url: str, timeout: float = 5.0) -> str:
    request = Request(url, headers={"User-Agent": "Hermes-Agent-status/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read(32_000).decode("utf-8", errors="replace").strip()


def _public_ip_and_geo() -> tuple[str, str]:
    try:
        public_ip = _http_get("https://api.ipify.org", timeout=5.0).splitlines()[0].strip()
        if not re.fullmatch(r"[0-9a-fA-F:.]+", public_ip):
            return "未知", "公网 IP 返回格式异常"
    except Exception as exc:
        return "未知", f"公网 IP 查询失败（{type(exc).__name__}）"

    try:
        raw = json.loads(_http_get(f"https://ipwho.is/{public_ip}", timeout=5.0))
        if raw.get("success") is False:
            return public_ip, "属地查询失败"
        parts = [raw.get("city"), raw.get("region"), raw.get("country")]
        location = ", ".join(str(part) for part in parts if part) or "未知"
        return public_ip, f"{location}（近似）"
    except Exception as exc:
        return public_ip, f"属地查询失败（{type(exc).__name__}）"


def _read_codex_radar(timeout: float = 10.0) -> dict[str, Any]:
    """Read Codex Radar public quota calibration, falling back to the last cache."""
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    cache_path = home / "cache" / "codexradar-current.json"
    try:
        request = Request(
            "https://codexradar.com/current.json",
            headers={"User-Agent": "Hermes-Agent-status/1.1", "Accept": "application/json"},
        )
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(2 * 1024 * 1024).decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return data
    except Exception:
        pass
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return cached if isinstance(cached, dict) else {}
    except Exception:
        return {}


def _equivalent_usd_remaining(rate: dict[str, Any], radar: dict[str, Any]) -> float | None:
    """Convert the active Codex allowance into Codex Radar API-equivalent USD."""
    plan = str(rate.get("planType") or "").strip().lower()
    target = "20x pro" if "pro" in plan else "plus" if "plus" in plan else ""
    primary = rate.get("primary") if isinstance(rate.get("primary"), dict) else {}
    used = primary.get("usedPercent")
    if not target or not isinstance(used, (int, float)):
        return None
    model_iq_raw = radar.get("model_iq")
    model_iq = model_iq_raw if isinstance(model_iq_raw, dict) else {}
    quota_raw = model_iq.get("quota_radar")
    quota = quota_raw if isinstance(quota_raw, dict) else {}
    rows_raw = quota.get("rows")
    rows = rows_raw if isinstance(rows_raw, list) else []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("tier") or "").strip().lower() != target:
            continue
        weekly_total = row.get("seven_d")
        if isinstance(weekly_total, (int, float)):
            remaining_percent = max(0.0, min(100.0, 100.0 - float(used)))
            return float(weekly_total) * remaining_percent / 100.0
    return None


def _codex_command() -> list[str] | None:
    configured = os.environ.get("CODEX_EXECUTABLE", "").strip()
    candidates = [configured] if configured else []
    candidates.extend(["codex", "codex.cmd"])
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate) or (candidate if os.path.exists(candidate) else None)
        if resolved:
            return [resolved]
    # Windows Codex is commonly exposed only through PowerShell from WSL.
    if shutil.which("pwsh.exe"):
        return ["pwsh.exe", "-NoProfile", "-Command", "codex"]
    return None


def _auth_error(stderr: str) -> str | None:
    lowered = stderr.lower()
    if "refresh_token_reused" in lowered or "refresh token was already used" in lowered:
        return "Codex OAuth 刷新令牌已失效或被重复使用，请执行 codex logout && codex login"
    if "unauthorized" in lowered or "failed to refresh token" in lowered:
        return "Codex OAuth 鉴权失败，请执行 codex logout && codex login"
    return None


def _read_codex_rate_limits(timeout: float = 15.0) -> dict[str, Any]:
    """Read Codex limits without blocking forever on a silent app-server.

    Codex app-server uses JSONL over stdio. ``readline()`` alone cannot enforce
    a deadline when the child emits no newline, so a selector is used around
    stdout. Stderr is collected after termination to turn OAuth failures into a
    useful user-facing diagnosis instead of the old generic error.
    """
    command = _codex_command()
    if not command:
        return {"error_code": "missing_cli", "error": "未找到 Codex CLI"}

    process = subprocess.Popen(
        command + ["app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    initialize = {
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "hermes-status", "title": "Hermes Status", "version": "1.1.0"},
            "capabilities": {"experimentalApi": True},
        },
    }
    deadline = time.monotonic() + timeout
    result: dict[str, Any] | None = None
    try:
        assert process.stdin is not None
        process.stdin.write(json.dumps(initialize) + "\n")
        process.stdin.flush()
        initialized = False
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            events = selector.select(timeout=min(0.5, remaining))
            if not events:
                continue
            raw_line = process.stdout.readline()
            if not raw_line:
                break
            try:
                message = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == 1 and not initialized:
                process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
                process.stdin.write(json.dumps({"id": 2, "method": "account/rateLimits/read", "params": None}) + "\n")
                process.stdin.flush()
                initialized = True
            elif message.get("id") == 2:
                if isinstance(message.get("error"), dict):
                    error = message["error"].get("message") or "Codex 额度接口返回错误"
                    result = {"error_code": "api_error", "error": str(error)}
                else:
                    result = message.get("result") or {"error_code": "empty_result", "error": "Codex 未返回额度"}
                break
        if result is None:
            result = {"error_code": "timeout", "error": "Codex 额度查询超时"}
    except (OSError, AssertionError) as exc:
        result = {"error_code": "process_error", "error": f"Codex 查询失败（{type(exc).__name__}）"}
    finally:
        try:
            selector.close()
        except Exception:
            pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            stderr = process.communicate(timeout=2)[1]
        except (OSError, subprocess.TimeoutExpired):
            stderr = ""
        auth_error = _auth_error(stderr or "")
        if auth_error:
            result = {"error_code": "auth", "error": auth_error}
    return result or {"error_code": "unknown", "error": "Codex 额度查询失败"}


def collect_status(*, model: str = "", provider: str = "") -> StatusSnapshot:
    public_ip, location = _public_ip_and_geo()
    network = {
        "proxy": _proxy_info(),
        "local_ip": _local_ip(),
        "public_ip": public_ip,
        "location": location,
    }
    return StatusSnapshot(
        model=model or os.environ.get("HERMES_MODEL", "未知"),
        provider=provider or os.environ.get("HERMES_PROVIDER", "未知"),
        codex=_read_codex_rate_limits(),
        codex_radar=_read_codex_radar(),
        network=network,
    )


def _append_rate_limit(lines: list[str], label: str, window: dict[str, Any] | None) -> None:
    if not isinstance(window, dict):
        return
    used = window.get("usedPercent")
    reset = _fmt_time(window.get("resetsAt"))
    lines.append(f"  {label}：已用 {used if used is not None else '未知'}%；{_remaining(used)}；重置 {reset}")


def _append_rate_windows(
    lines: list[str],
    primary: dict[str, Any] | None,
    secondary: dict[str, Any] | None,
) -> None:
    """Render quota windows without assuming OpenAI's current duration labels."""
    windows = [window for window in (primary, secondary) if isinstance(window, dict)]
    for index, window in enumerate(windows, start=1):
        label = "额度" if len(windows) == 1 else f"额度 {index}"
        _append_rate_limit(lines, label, window)


def _append_reset_credits(lines: list[str], reset_credits: Any) -> None:
    """Render every Codex rate-limit reset credit and its expiry time."""
    if not isinstance(reset_credits, dict):
        return
    raw_credits = reset_credits.get("credits")
    credits = raw_credits if isinstance(raw_credits, list) else []
    available = reset_credits.get("availableCount")
    if available is None:
        available = sum(
            1 for credit in credits if isinstance(credit, dict) and credit.get("status") == "available"
        )
    lines.append("  额度重置：")
    lines.append(f"    可用次数：{available}")
    if raw_credits is None:
        lines.append("    到期时间：Codex 接口本次未提供")
        return
    lines.append(f"    详情条数：{len(credits)}")
    status_names = {
        "available": "可用",
        "redeeming": "使用中",
        "redeemed": "已使用",
        "unknown": "未知",
    }
    for index, credit in enumerate(credits, start=1):
        if not isinstance(credit, dict):
            continue
        status = status_names.get(str(credit.get("status", "")).lower(), credit.get("status") or "未知")
        lines.append(
            f"    第 {index} 次：{status}；发放 {_fmt_time(credit.get('grantedAt'))}；"
            f"到期 {_fmt_time(credit.get('expiresAt'))}"
        )


def render_status(snapshot: StatusSnapshot) -> str:
    lines = ["Hermes 状态", f"  模型：{snapshot.model or '未知'}", f"  Provider：{snapshot.provider or '未知'}", ""]
    codex = snapshot.codex or {}
    rate = codex.get("rateLimits") if isinstance(codex, dict) else None
    if isinstance(rate, dict):
        lines.extend(["Codex 账号", f"  套餐：{rate.get('planType') or '未知'}"])
        _append_rate_windows(lines, rate.get("primary"), rate.get("secondary"))
        equivalent_usd = _equivalent_usd_remaining(rate, snapshot.codex_radar or {})
        if equivalent_usd is None:
            lines.append("  等效剩余价值：未知")
        else:
            lines.append(f"  等效剩余价值：约 US${equivalent_usd:,.2f}")
        lines.append(f"  状态：{'已触发限额' if rate.get('rateLimitReachedType') else '正常'}")
        _append_reset_credits(lines, codex.get("rateLimitResetCredits"))
        by_id = codex.get("rateLimitsByLimitId") or {}
        spark = by_id.get("codex_bengalfox") if isinstance(by_id, dict) else None
        if isinstance(spark, dict):
            lines.append("  Spark：")
            _append_rate_windows(lines, spark.get("primary"), spark.get("secondary"))
    else:
        error = codex.get("error", "查询失败") if isinstance(codex, dict) else "查询失败"
        lines.append(f"Codex 额度：{error}")

    provider = snapshot.provider.lower()
    if "codex" not in provider and "openai" not in provider:
        lines.extend(["", "Provider 额度", "  当前仅能读取 Codex OAuth 额度；API Key provider 的余额/限额需到对应服务商控制台查询。"])

    network = snapshot.network or {}
    lines.extend([
        "",
        "网络",
        f"  代理：{network.get('proxy', '未知')}",
        f"  本机 IP：{network.get('local_ip', '未知')}",
        f"  公网 IP：{network.get('public_ip', '未知')}",
        f"  属地：{network.get('location', '未知')}",
        "",
        "说明：公网 IP 属地为近似结果；代理凭据不会显示；每次执行都会重新探测。",
    ])
    return "\n".join(lines)
