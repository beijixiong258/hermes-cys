from hermes_cli.system_status import StatusSnapshot, _auth_error, _safe_proxy, render_status


def test_safe_proxy_removes_userinfo_and_password():
    assert _safe_proxy("http://user:secret@127.0.0.1:7890") == "http://127.0.0.1:7890"


def test_render_status_includes_quota_and_network_without_secrets():
    snapshot = StatusSnapshot(
        model="gpt-5.6-luna",
        provider="openai-codex",
        codex={
            "rateLimits": {
                "planType": "pro",
                "primary": {"usedPercent": 10, "resetsAt": 1783699463},
                "secondary": {"usedPercent": 18, "resetsAt": 1784246043},
                "credits": {"balance": "0"},
            },
            "rateLimitsByLimitId": {
                "codex_bengalfox": {
                    "primary": {"usedPercent": 0, "resetsAt": 1783699463},
                    "secondary": {"usedPercent": 0, "resetsAt": 1784246043},
                }
            },
            "rateLimitResetCredits": {
                "availableCount": 2,
                "credits": [
                    {"status": "available", "grantedAt": 1782936230, "expiresAt": 1785528230},
                    {"status": "redeemed", "grantedAt": 1783965003, "expiresAt": 1786557003},
                ],
            },
        },
        codex_radar={
            "model_iq": {
                "quota_radar": {
                    "rows": [{"tier": "20x Pro", "seven_d": 1722.06}]
                }
            }
        },
        network={
            "proxy": "HTTP_PROXY=http://127.0.0.1:7890",
            "local_ip": "192.168.1.2",
            "public_ip": "203.0.113.5",
            "location": "Beijing, China（近似）",
        },
    )
    output = render_status(snapshot)
    assert "套餐：pro" in output
    assert "额度 1：已用 10%；剩余 90%" in output
    assert "额度 2：已用 18%；剩余 82%" in output
    assert "5 小时" not in output
    assert "7 天" not in output
    assert "等效剩余价值：约 US$1,549.85" in output
    assert "Credits：0" not in output
    assert "可用次数：2" in output
    assert "详情条数：2" in output
    assert "第 1 次：可用；发放 " in output
    assert "第 2 次：已使用；发放 " in output
    assert output.count("；到期 ") == 2
    assert "公网 IP：203.0.113.5" in output
    assert "代理凭据不会显示" in output
    assert "secret" not in output


def test_auth_error_explains_rotating_refresh_token_failure():
    message = _auth_error("Failed to refresh token: refresh_token_reused")
    assert message == "Codex OAuth 刷新令牌已失效或被重复使用，请执行 codex logout && codex login"


def test_render_status_explains_non_codex_provider_limitations():
    output = render_status(
        StatusSnapshot(
            model="deepseek-chat",
            provider="deepseek",
            codex={"error_code": "missing_cli", "error": "未找到 Codex CLI"},
            network={},
        )
    )
    assert "当前仅能读取 Codex OAuth 额度" in output
    assert "API Key provider" in output


def test_render_status_handles_missing_used_percent():
    output = render_status(
        StatusSnapshot(
            model="gpt-5.6-luna",
            provider="openai-codex",
            codex={"rateLimits": {"primary": {"resetsAt": 1783699463}}},
            network={},
        )
    )
    assert "额度：已用 未知%；剩余 未知" in output


def test_render_status_derives_available_reset_count_when_api_omits_it():
    output = render_status(
        StatusSnapshot(
            model="gpt-5.6-luna",
            provider="openai-codex",
            codex={
                "rateLimits": {},
                "rateLimitResetCredits": {
                    "credits": [
                        {"status": "available", "expiresAt": 1785528230},
                        {"status": "redeemed", "expiresAt": 1786557003},
                    ]
                },
            },
            network={},
        )
    )
    assert "可用次数：1" in output
    assert "详情条数：2" in output
    assert "第 2 次：已使用" in output


def test_render_status_reports_when_reset_expiry_details_are_unavailable():
    output = render_status(
        StatusSnapshot(
            model="gpt-5.6-sol",
            provider="openai-codex",
            codex={
                "rateLimits": {},
                "rateLimitResetCredits": {"availableCount": 2, "credits": None},
            },
            network={},
        )
    )
    assert "可用次数：2" in output
    assert "到期时间：Codex 接口本次未提供" in output
