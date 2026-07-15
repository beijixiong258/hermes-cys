from __future__ import annotations

import base64
import contextlib
import json
import os
import queue
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_SECRET_KEYS = {"api_key", "access_token", "refresh_token", "id_token", "token", "password", "cookie", "authorization"}


def _now_line() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        p = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return (p.stdout or "").strip()
    except Exception as exc:
        return f"不可用：{type(exc).__name__}: {exc}"


def _mask_middle(value: Any, keep: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= keep * 2 + 1:
        return text
    return f"{text[:keep]}…{text[-keep:]}"


def _redact_proxy(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "未设置"
    # Remove credentials in scheme://user:pass@host:port
    try:
        parsed = urllib.parse.urlsplit(text if "://" in text else "http://" + text)
        if parsed.username or parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc += f":{parsed.port}"
            rebuilt = urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
            return rebuilt.replace("http://", "", 1) if "://" not in text else rebuilt
    except Exception:
        pass
    return re.sub(r"//[^/@\s]+@", "//***@", text)


def _env_proxy_map() -> dict[str, str]:
    keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"]
    return {k: os.environ.get(k, "") for k in keys if os.environ.get(k)}


def _powershell_proxy() -> dict[str, Any]:
    script = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$p = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
$winhttp = (netsh winhttp show proxy 2>$null | Out-String).Trim()
[pscustomobject]@{
  ProxyEnable = if ($null -ne $p.ProxyEnable) { [int]$p.ProxyEnable } else { 0 }
  ProxyServer = [string]$p.ProxyServer
  AutoConfigURL = [string]$p.AutoConfigURL
  WinHTTP = [string]$winhttp
} | ConvertTo-Json -Compress
""".strip()
    out = _run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=4.0)
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"error": out}


def _parse_proxy_candidates(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    pieces: list[str] = []
    # WinINET may be: http=127.0.0.1:7890;https=127.0.0.1:7890 or just host:port
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part and not part.lower().startswith(("http://", "https://", "socks")):
            _scheme, value = part.split("=", 1)
            part = value.strip()
        if part:
            pieces.append(part)
    if not pieces:
        pieces.append(raw)
    result: list[str] = []
    for item in pieces:
        if not item:
            continue
        result.append(item if "://" in item else "http://" + item)
    return result


def _choose_proxy(env_map: dict[str, str], win_proxy: dict[str, Any]) -> str:
    for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        value = env_map.get(key)
        if value:
            return value
    if int(win_proxy.get("ProxyEnable") or 0) == 1:
        candidates = _parse_proxy_candidates(str(win_proxy.get("ProxyServer") or ""))
        if candidates:
            return candidates[0]
    return ""


def _proxy_endpoint(proxy_url: str) -> tuple[str, int] | None:
    if not proxy_url:
        return None
    try:
        parsed = urllib.parse.urlsplit(proxy_url if "://" in proxy_url else "http://" + proxy_url)
        host = parsed.hostname
        port = parsed.port
        if host and port:
            return host, int(port)
    except Exception:
        return None
    return None


def _tcp_check(host: str, port: int, timeout: float = 0.8) -> str:
    started = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return f"可连接（{int((time.time() - started) * 1000)}ms）"
    except Exception as exc:
        return f"不可连接：{type(exc).__name__}"


def _local_ips() -> list[str]:
    out = _run(["ip", "-o", "-4", "addr", "show", "scope", "global"], timeout=2.0)
    rows: list[str] = []
    for line in out.splitlines():
        m = re.search(r"^\d+:\s+([^\s]+).*?\sinet\s+([^\s]+)", line)
        if m:
            rows.append(f"{m.group(1)} {m.group(2)}")
    if rows:
        return rows
    # Portable fallback.
    try:
        name = socket.gethostname()
        addrs = sorted({x[4][0] for x in socket.getaddrinfo(name, None, socket.AF_INET)})
        return addrs or ["未发现"]
    except Exception as exc:
        return [f"不可用：{type(exc).__name__}: {exc}"]


def _default_route() -> str:
    out = _run(["ip", "route", "get", "1.1.1.1"], timeout=2.0)
    return out.splitlines()[0] if out else "不可用"


def _fetch_json(
    url: str,
    proxy_url: str = "",
    timeout: float = 8.0,
    max_bytes: int = 64 * 1024,
) -> tuple[dict[str, Any] | None, str]:
    handlers = []
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-zhuangtai/1.1", "Accept": "application/json"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read(max_bytes).decode("utf-8", errors="replace")
        parsed = json.loads(data)
        if isinstance(parsed, dict):
            return parsed, ""
        return None, "响应不是 JSON 对象"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _public_geo(proxy_url: str) -> dict[str, Any]:
    data, err = _fetch_json("https://ipapi.co/json/", proxy_url=proxy_url, timeout=8.0)
    if data and data.get("ip"):
        return {
            "ip": data.get("ip"),
            "location": "/".join(str(x) for x in [data.get("country_name"), data.get("region"), data.get("city")] if x),
            "org": data.get("org") or data.get("asn"),
            "timezone": data.get("timezone"),
            "source": "ipapi.co",
        }
    data2, err2 = _fetch_json("https://ipwho.is/", proxy_url=proxy_url, timeout=8.0)
    if data2 and data2.get("success", True) and data2.get("ip"):
        return {
            "ip": data2.get("ip"),
            "location": "/".join(str(x) for x in [data2.get("country"), data2.get("region"), data2.get("city")] if x),
            "org": ((data2.get("connection") or {}).get("org") if isinstance(data2.get("connection"), dict) else None),
            "timezone": ((data2.get("timezone") or {}).get("id") if isinstance(data2.get("timezone"), dict) else None),
            "source": "ipwho.is",
        }
    return {"error": err2 or err or "公网 IP 查询失败"}


@contextlib.contextmanager
def _temporary_proxy_env(proxy_url: str):
    keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
    old = {k: os.environ.get(k) for k in keys}
    if proxy_url:
        for k in keys:
            os.environ[k] = proxy_url
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _format_host(url: Any) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme and parsed.netloc:
            return parsed.netloc
    except Exception:
        pass
    return text


def _load_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _agent_from_ctx(ctx: Any):
    try:
        cli = getattr(getattr(ctx, "_manager", None), "_cli_ref", None)
        return getattr(cli, "agent", None), cli
    except Exception:
        return None, None


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    token = str(token or "")
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        body = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _format_exp(value: Any) -> str:
    try:
        ts = int(value)
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return ""


def _safe_auth_identity(provider: str) -> list[str]:
    provider = (provider or "").strip().lower()
    if not provider:
        return ["账号：未知（没有 provider）"]
    try:
        from hermes_cli.auth import get_provider_auth_state

        state = get_provider_auth_state(provider) or {}
    except Exception as exc:
        return [f"账号：读取失败：{type(exc).__name__}: {exc}"]
    if not state:
        return ["账号：未发现本地登录状态"]

    lines: list[str] = []
    auth_mode = state.get("auth_mode") or state.get("source") or "Hermes auth store"
    lines.append(f"账号来源：{auth_mode}")
    last_refresh = state.get("last_refresh")
    if last_refresh:
        lines.append(f"最近刷新：{last_refresh}")

    tokens = state.get("tokens") if isinstance(state.get("tokens"), dict) else {}
    id_payload = _decode_jwt_payload(str(tokens.get("id_token") or ""))
    access_payload = _decode_jwt_payload(str(tokens.get("access_token") or ""))
    merged: dict[str, Any] = {}
    # Identity fields are usually clearer in id_token; access_token often has
    # the longer-lived runtime expiry. Keep those concepts separate so the
    # status page does not report an expired id_token as the active access token.
    for p in (id_payload, access_payload):
        for k, v in p.items():
            merged.setdefault(k, v)
    profile = access_payload.get("https://api.openai.com/profile") or merged.get("https://api.openai.com/profile")
    if isinstance(profile, dict):
        for k, v in profile.items():
            merged.setdefault(k, v)

    email = state.get("email") or tokens.get("email") or id_payload.get("email") or merged.get("email")
    name = state.get("name") or tokens.get("name") or id_payload.get("name") or merged.get("name")
    account_id = tokens.get("account_id") or state.get("account_id") or merged.get("account_id")
    sub = id_payload.get("sub") or merged.get("sub")
    exp = access_payload.get("exp") or merged.get("exp")

    if email:
        lines.append(f"账号邮箱：{email}")
    if name:
        lines.append(f"账号名称：{name}")
    if account_id:
        lines.append(f"账号 ID：{_mask_middle(account_id, 6)}")
    if sub:
        lines.append(f"主体 ID：{_mask_middle(sub, 8)}")
    exp_text = _format_exp(exp)
    if exp_text:
        lines.append(f"访问令牌到期：{exp_text}")
    if len(lines) == 1:
        safe_keys = [k for k in sorted(state.keys()) if k.lower() not in _SECRET_KEYS and k != "tokens"]
        if safe_keys:
            lines.append("可见字段：" + ", ".join(safe_keys))
    return lines


def _session_usage_lines(agent: Any, cli: Any) -> list[str]:
    if agent is None:
        return ["会话用量：当前上下文没有 live agent（重开 Hermes 后在聊天中运行 /zhuangtai 可见）"]
    lines = []
    calls = getattr(agent, "session_api_calls", 0) or 0
    input_tokens = getattr(agent, "session_input_tokens", 0) or 0
    output_tokens = getattr(agent, "session_output_tokens", 0) or 0
    reasoning_tokens = getattr(agent, "session_reasoning_tokens", 0) or 0
    prompt_tokens = getattr(agent, "session_prompt_tokens", 0) or 0
    completion_tokens = getattr(agent, "session_completion_tokens", 0) or 0
    total_tokens = getattr(agent, "session_total_tokens", 0) or 0
    lines.append(f"会话 API 调用：{calls}")
    lines.append(f"会话 tokens：input {input_tokens:,} / output {output_tokens:,} / total {total_tokens:,}")
    if reasoning_tokens:
        lines.append(f"推理 tokens：{reasoning_tokens:,}")
    if prompt_tokens or completion_tokens:
        lines.append(f"Prompt/Completion：{prompt_tokens:,} / {completion_tokens:,}")
    compressor = getattr(agent, "context_compressor", None)
    if compressor is not None:
        last_prompt = getattr(compressor, "last_prompt_tokens", 0) or 0
        ctx_len = getattr(compressor, "context_length", 0) or 0
        if ctx_len:
            pct = min(100.0, last_prompt / ctx_len * 100.0)
            lines.append(f"当前上下文：{last_prompt:,} / {ctx_len:,} ({pct:.0f}%)")
        comp = getattr(compressor, "compression_count", 0) or 0
        lines.append(f"压缩次数：{comp}")
    return lines


def _fetch_account_usage(
    provider: str,
    base_url: str,
    api_key: str,
    proxy_url: str,
) -> tuple[list[str], Any]:
    if not provider:
        return ["账号用量：未知（没有 provider）"], None
    try:
        from agent.account_usage import fetch_account_usage, render_account_usage_lines

        with _temporary_proxy_env(proxy_url):
            snap = fetch_account_usage(provider, base_url=base_url or None, api_key=api_key or None)
        rendered = render_account_usage_lines(snap)
        rendered = [
            "额外充值余额：US$0（仅指另购 Credits，不含 Pro 套餐额度）"
            if re.fullmatch(r"Credits balance:\s*\$0(?:\.0+)?", line.strip(), flags=re.IGNORECASE)
            else line
            for line in rendered
        ]
        lines = rendered if rendered else ["账号用量：该 provider 未提供，或当前接口不可用"]
        return lines, snap
    except Exception as exc:
        return [f"账号用量：读取失败：{type(exc).__name__}: {exc}"], None


def _runtime_model_lines(agent: Any, cfg: dict[str, Any]) -> tuple[list[str], str, str, str]:
    model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    cfg_provider = str(model_cfg.get("provider") or "").strip()
    cfg_model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
    cfg_base = str(model_cfg.get("base_url") or "").strip()

    provider = str(getattr(agent, "provider", "") or cfg_provider).strip()
    model = str(getattr(agent, "model", "") or cfg_model).strip()
    base_url = str(getattr(agent, "base_url", "") or cfg_base).strip()
    api_mode = str(getattr(agent, "api_mode", "") or "").strip()

    lines = []
    lines.append(f"会话模型：{model or '未知'}")
    lines.append(f"会话 provider：{provider or '未知'}")
    if api_mode:
        lines.append(f"API 模式：{api_mode}")
    if base_url:
        lines.append(f"接口地址：{_format_host(base_url)}")
    if cfg_provider or cfg_model:
        cfg_piece = f"{cfg_provider or 'auto'} / {cfg_model or '未设置'}"
        alias = str(model_cfg.get("model") or "").strip()
        if alias and alias != cfg_model:
            cfg_piece += f"（model 字段：{alias}）"
        lines.append(f"配置模型：{cfg_piece}")
    try:
        from hermes_cli.runtime_provider import resolve_runtime_provider

        runtime = resolve_runtime_provider(requested=cfg_provider or None, target_model=model or None)
        rt_provider = runtime.get("provider") or ""
        rt_source = runtime.get("source") or ""
        rt_api_mode = runtime.get("api_mode") or ""
        if rt_provider or rt_source or rt_api_mode:
            parts = []
            if rt_provider:
                parts.append(f"provider={rt_provider}")
            if rt_source:
                parts.append(f"source={rt_source}")
            if rt_api_mode:
                parts.append(f"api_mode={rt_api_mode}")
            lines.append("运行时解析：" + " / ".join(parts))
    except Exception as exc:
        lines.append(f"运行时解析：失败：{type(exc).__name__}: {exc}")
    return lines, provider, base_url, str(getattr(agent, "api_key", "") or "")


def _dedupe(seq: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _reasoning_effort(agent: Any, cfg: dict[str, Any]) -> str:
    live = str(getattr(agent, "reasoning_effort", "") or "").strip().lower()
    if live:
        return live
    agent_cfg = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}
    return str(agent_cfg.get("reasoning_effort") or "").strip().lower()


def _fetch_codex_radar(proxy_url: str) -> tuple[dict[str, Any] | None, str]:
    data, error = _fetch_json(
        "https://codexradar.com/current.json",
        proxy_url=proxy_url,
        timeout=10.0,
        max_bytes=2 * 1024 * 1024,
    )
    try:
        from hermes_constants import get_hermes_home

        cache_path = Path(get_hermes_home()) / "cache" / "codexradar-current.json"
    except Exception:
        cache_path = Path.home() / ".hermes" / "cache" / "codexradar-current.json"
    if data:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = cache_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(cache_path)
        except Exception:
            pass
        return data, ""
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, dict):
            cached["_zhuangtai_cache_notice"] = f"实时连接失败，正在使用最近缓存（{error}）"
            return cached, ""
    except Exception:
        pass
    return None, error


def _radar_model_entry(data: dict[str, Any], model: str, effort: str) -> dict[str, Any]:
    model_iq = data.get("model_iq") if isinstance(data.get("model_iq"), dict) else {}
    candidates = []
    latest = model_iq.get("latest")
    if isinstance(latest, dict):
        candidates.append(latest)
    comparisons = model_iq.get("comparisons")
    if isinstance(comparisons, dict):
        for comparison in comparisons.values():
            if isinstance(comparison, dict) and isinstance(comparison.get("latest"), dict):
                candidates.append(comparison["latest"])
    normalized_model = model.strip().lower()
    normalized_effort = effort.strip().lower()
    for candidate in candidates:
        if (
            str(candidate.get("model") or "").strip().lower() == normalized_model
            and str(candidate.get("reasoning_effort") or "").strip().lower() == normalized_effort
        ):
            return candidate
    for candidate in candidates:
        if str(candidate.get("model") or "").strip().lower() == normalized_model:
            return candidate
    return latest if isinstance(latest, dict) else {}


def _quota_row_for_plan(rows: Any, plan: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    normalized = str(plan or "").strip().lower()
    target = ""
    if "plus" in normalized:
        target = "plus"
    elif "pro" in normalized:
        # ChatGPT Pro maps to the site's measured 20x Pro tier.
        target = "20x pro"
    if not target:
        return {}
    for row in rows:
        if isinstance(row, dict) and str(row.get("tier") or "").strip().lower() == target:
            return row
    return {}


def _weekly_remaining_percent(snapshot: Any, *, five_hour_paused: bool = False) -> float | None:
    windows = tuple(getattr(snapshot, "windows", ()) or ())
    for window in windows:
        if str(getattr(window, "label", "") or "").strip().lower() == "weekly":
            used = getattr(window, "used_percent", None)
            if isinstance(used, (int, float)):
                return max(0.0, min(100.0, 100.0 - float(used)))
    # OpenAI currently returns the active 7-day window in primary_window while
    # the 5-hour window is paused; Hermes renders that primary slot as Session.
    if five_hour_paused and len(windows) == 1:
        used = getattr(windows[0], "used_percent", None)
        if isinstance(used, (int, float)):
            return max(0.0, min(100.0, 100.0 - float(used)))
    return None


def _codex_radar_lines(
    data: dict[str, Any],
    model: str,
    effort: str,
    usage_snapshot: Any,
) -> list[str]:
    lines: list[str] = []
    window = data.get("window") if isinstance(data.get("window"), dict) else {}
    prediction = data.get("prediction") if isinstance(data.get("prediction"), dict) else {}
    model_iq = data.get("model_iq") if isinstance(data.get("model_iq"), dict) else {}
    entry = _radar_model_entry(data, model, effort)

    message = str(window.get("message") or "状态暂无说明")
    action = str(window.get("action") or data.get("recommended_action") or "未知")
    lines.append(f"重置雷达：{message}（建议：{action}）")
    p24 = prediction.get("probability_24h")
    p48 = prediction.get("probability_48h")
    if isinstance(p24, (int, float)) and isinstance(p48, (int, float)):
        lines.append(
            f"硬重置预测：24h {float(p24) * 100:.0f}% / 48h {float(p48) * 100:.0f}%"
            f"（{prediction.get('level') or 'unknown'}）"
        )

    if entry:
        status = str(entry.get("status") or "unknown").lower()
        score = entry.get("score")
        label = f"{entry.get('model') or model} / {entry.get('reasoning_effort') or effort}"
        score_text = f"{float(score):.0f}" if isinstance(score, (int, float)) else "未知"
        lines.append(
            f"模型智力：{label} = {score_text} 分，"
            f"通过 {entry.get('passed', '?')}/{entry.get('tasks', '?')}（{entry.get('date', '未知批次')}）"
        )
        if status == "red":
            lines.append("降智预警：🚨 红色，公开基准明显异常，重要任务建议暂缓或换档复测。")
        elif status == "yellow":
            lines.append("降智预警：⚠️ 黄色，公开基准低于正常区间，重要结果建议加强复核。")
        elif status == "green":
            lines.append("降智预警：正常（绿色），当前公开基准未触发降智警报。")
        else:
            lines.append(f"降智预警：状态未知（{status}），请勿据此判断模型质量。")
    else:
        lines.append("降智预警：网站暂无当前模型/推理档位的基准数据。")

    quota = model_iq.get("quota_radar") if isinstance(model_iq.get("quota_radar"), dict) else {}
    plan = str(getattr(usage_snapshot, "plan", "") or "")
    row = _quota_row_for_plan(quota.get("rows"), plan)
    if row:
        weekly_total = row.get("seven_d")
        five_hour_paused = quota.get("five_hour_policy") == "temporarily_paused_hidden"
        remaining_pct = _weekly_remaining_percent(
            usage_snapshot,
            five_hour_paused=five_hour_paused,
        )
        if isinstance(weekly_total, (int, float)):
            if remaining_pct is not None:
                remaining_usd = float(weekly_total) * remaining_pct / 100.0
                lines.append(f"套餐剩余等效 Credits：约 {remaining_usd:,.2f} credits（剩余 {remaining_pct:.0f}%）")
                lines.append(
                    f"地球 OL 货币价值：约 US${remaining_usd:,.2f} / 每周总值 US${float(weekly_total):,.2f}"
                    f"（{row.get('tier')}）"
                )
            else:
                lines.append(
                    f"套餐等效 Credits：约 {float(weekly_total):,.2f} credits/周（{row.get('tier')}；账号剩余比例不可用）"
                )
    else:
        lines.append("等效 API 额度：当前账号套餐无法映射到网站的 Plus/Pro 估算档位。")
    if quota.get("five_hour_policy") == "temporarily_paused_hidden":
        lines.append("5 小时额度：网站标记为临时暂停，当前按 7 天窗口估算。")
    updated = quota.get("updated_at") or data.get("monitored_at")
    if updated:
        lines.append(f"雷达数据时间：{updated}")
    lines.append("说明：等效 API 额度和降智判断均为第三方公开估算，不是 OpenAI 官方承诺。")
    lines.append("换算口径：1 等效 credit = US$1 的 API 调用价值；Credits 0 仅指额外充值余额，不含 Pro 套餐额度。")
    cache_notice = data.get("_zhuangtai_cache_notice")
    if cache_notice:
        lines.append(f"雷达连接：{cache_notice}")
    lines.append("数据来自 Codex 雷达 codexradar.com：https://codexradar.com/")
    return lines


def build_status_text(ctx: Any = None) -> str:
    env_map = _env_proxy_map()
    win_proxy = _powershell_proxy()
    proxy_url = _choose_proxy(env_map, win_proxy)

    # Network geolocation can be slow; run it in a bounded helper thread.
    q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)

    def _geo_worker():
        try:
            q.put(_public_geo(proxy_url), block=False)
        except Exception as exc:
            q.put({"error": f"{type(exc).__name__}: {exc}"}, block=False)

    t = threading.Thread(target=_geo_worker, name="zhuangtai-geo", daemon=True)
    t.start()
    try:
        geo = q.get(timeout=9.0)
    except queue.Empty:
        geo = {"error": "公网 IP/归属地查询超时"}

    cfg = _load_config()
    agent, cli = _agent_from_ctx(ctx)
    model_lines, provider, base_url, api_key = _runtime_model_lines(agent, cfg)

    lines: list[str] = []
    lines.append("zhuangtai 状态")
    lines.append(f"时间：{_now_line()}")
    lines.append("")

    lines.append("网络")
    for row in _local_ips():
        lines.append(f"本机 IP：{row}")
    lines.append(f"默认路由：{_default_route()}")
    if geo.get("error"):
        lines.append(f"公网 IP：不可用（{geo.get('error')}）")
    else:
        lines.append(f"公网 IP：{geo.get('ip') or '未知'}")
        lines.append(f"归属地：{geo.get('location') or '未知'}")
        if geo.get("org"):
            lines.append(f"运营商/组织：{geo.get('org')}")
        if geo.get("timezone"):
            lines.append(f"时区：{geo.get('timezone')}")
        lines.append(f"归属地来源：{geo.get('source')}")
    lines.append("")

    lines.append("代理")
    if env_map:
        for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"]:
            if key in env_map:
                value = env_map[key]
                if "proxy" in key.lower() and key.lower() != "no_proxy":
                    value = _redact_proxy(value)
                lines.append(f"{key}：{value}")
    else:
        lines.append("环境变量代理：未设置")
    if "error" in win_proxy:
        lines.append(f"Windows 系统代理：读取失败：{win_proxy.get('error')}")
    else:
        enabled = "开" if int(win_proxy.get("ProxyEnable") or 0) == 1 else "关"
        lines.append(f"Windows WinINET：{enabled} / {_redact_proxy(win_proxy.get('ProxyServer'))}")
        if win_proxy.get("AutoConfigURL"):
            lines.append(f"Windows PAC：{win_proxy.get('AutoConfigURL')}")
        winhttp = str(win_proxy.get("WinHTTP") or "").replace("\r", "").strip()
        if winhttp:
            short = " ".join(x.strip() for x in winhttp.splitlines() if x.strip())
            lines.append(f"Windows WinHTTP：{short}")
    lines.append(f"本次网络查询使用代理：{_redact_proxy(proxy_url) if proxy_url else '未使用'}")
    candidates = []
    candidates.extend(_parse_proxy_candidates(env_map.get("HTTPS_PROXY") or env_map.get("https_proxy") or ""))
    candidates.extend(_parse_proxy_candidates(env_map.get("HTTP_PROXY") or env_map.get("http_proxy") or ""))
    if int(win_proxy.get("ProxyEnable") or 0) == 1:
        candidates.extend(_parse_proxy_candidates(str(win_proxy.get("ProxyServer") or "")))
    for cand in _dedupe(candidates):
        ep = _proxy_endpoint(cand)
        if ep:
            lines.append(f"代理接口 {ep[0]}:{ep[1]}：{_tcp_check(ep[0], ep[1])}")
    lines.append("")

    lines.append("模型")
    lines.extend(model_lines)
    lines.append("")

    lines.append("账号")
    lines.extend(_safe_auth_identity(provider))
    lines.append("")

    lines.append("用量")
    lines.extend(_session_usage_lines(agent, cli))
    usage_lines, usage_snapshot = _fetch_account_usage(provider, base_url, api_key, proxy_url)
    lines.extend(usage_lines)
    lines.append("")

    lines.append("Codex 雷达")
    radar, radar_error = _fetch_codex_radar(proxy_url)
    if radar:
        live_model = str(getattr(agent, "model", "") or "")
        if not live_model:
            model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
            live_model = str(model_cfg.get("default") or model_cfg.get("model") or "")
        lines.extend(
            _codex_radar_lines(
                radar,
                live_model,
                _reasoning_effort(agent, cfg),
                usage_snapshot,
            )
        )
    else:
        lines.append(f"读取失败：{radar_error or '未知错误'}")
        lines.append("来源：https://codexradar.com/")

    # Defense-in-depth: do not let accidental secrets through if upstream shapes change.
    safe_text = "\n".join(lines)
    safe_text = re.sub(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|authorization)\s*[:=]\s*\S+", r"\1=<redacted>", safe_text)
    return safe_text
