---
name: hermes-wechat-setup
description: Connect Hermes Agent to personal WeChat (微信) via the iLink Bot API. Covers QR login, configuration, allowlists, and common pitfalls like pairing-mode DM policy and unauthorized user errors.
---

# Hermes WeChat (微信) Setup

Connect Hermes Agent to a personal WeChat account using Tencent's iLink Bot API.

## Prerequisites

- Python packages: `aiohttp` and `cryptography` (install in Hermes's venv)
- A personal WeChat account (手机微信扫码登录)

## Quick Setup

### 1. Install dependencies

```bash
/home/user/.hermes/hermes-agent/venv/bin/pip install aiohttp cryptography
pip install hermes-agent[messaging]   # optional: terminal QR display
```

### 2. Run setup wizard

```bash
hermes gateway setup
```

Select **Weixin / WeChat**. The wizard will:
1. Request QR code from iLink Bot API
2. Display QR code in terminal (or provide URL)
3. Wait for you to scan with WeChat mobile app and confirm login
4. Auto-save credentials to `~/.hermes/weixin/accounts/<account_id>.json`

### 3. Configure environment variables

In `~/.hermes/.env`:

```bash
# Required — auto-created by setup wizard
WEIXIN_ACCOUNT_ID=your_account_id@im.bot
WEIXIN_TOKEN=your_token

# Change from 'pairing' to 'open' after setup!
WEIXIN_DM_POLICY=open

# Add your WeChat user ID to allowlist
WEIXIN_ALLOWED_USERS=your_wechat_user_id@im.wechat

# Optional
WEIXIN_GROUP_POLICY=disabled     # keep disabled unless you want bot in groups
WEIXIN_HOME_CHANNEL=your_user_id@im.wechat
```

### 4. Start gateway

```bash
hermes gateway run
```

## Common Pitfalls

### "Unauthorized user" errors

After initial QR setup, `WEIXIN_DM_POLICY` defaults to `pairing`. Change it:

```bash
sed -i 's/WEIXIN_DM_POLICY=pairing/WEIXIN_DM_POLICY=open/' ~/.hermes/.env
```

Also ensure `WEIXIN_ALLOWED_USERS` includes your WeChat user ID (find it in gateway logs: `[Weixin] inbound from=XXXXX`).

### Gateway-level "Unauthorized" (not platform-specific)

If you see `No user allowlists configured. All unauthorized users will be denied`, ensure you have either:
- `GATEWAY_ALLOW_ALL_USERS=true` in `.env` — opens all platforms
- Or platform-specific allowlists (e.g., `WEIXIN_ALLOWED_USERS`, `TELEGRAM_ALLOWED_USERS`)

### Session expired (errcode=-14)

Token expired. Re-run `hermes gateway setup` to scan a new QR code.

### "aiohttp and cryptography are required"

Install in Hermes's venv, not system Python:

```bash
/home/user/.hermes/hermes-agent/venv/bin/pip install aiohttp cryptography
```

### Token lock: "Another local Hermes gateway is already using this Weixin token"

Only one gateway instance per token. Kill the old one first.

## Key Files

| Path | Purpose |
|------|---------|
| `~/.hermes/.env` | `WEIXIN_*` env vars |
| `~/.hermes/weixin/accounts/<id>.json` | Saved credentials from QR login |
| `~/.hermes/weixin/accounts/<id>.context-tokens.json` | Reply continuity tokens |
| `~/.hermes/logs/agent.log` | Gateway + WeChat connection logs |

## Features

- Long-poll transport (no public endpoint needed)
- QR login via `hermes gateway setup`
- DM and group messaging
- Media: images, video, files, voice
- AES-128-ECB encrypted CDN for media transfer
- Markdown formatting preserved
- Smart message chunking (single bubble under 4000 chars)
- Typing indicators ("正在输入…")
- 5-min message deduplication
- Auto-retry with backoff

## Configuration Reference

| Env var | Default | Description |
|---------|---------|-------------|
| `WEIXIN_ACCOUNT_ID` | _(required)_ | iLink Bot account ID from QR login |
| `WEIXIN_TOKEN` | _(required)_ | iLink Bot token |
| `WEIXIN_BASE_URL` | `https://ilinkai.weixin.qq.com` | API base URL |
| `WEIXIN_DM_POLICY` | `open` | DM access: open/allowlist/disabled/pairing |
| `WEIXIN_ALLOWED_USERS` | _(empty)_ | Comma-separated user IDs for DM allowlist |
| `WEIXIN_GROUP_POLICY` | `disabled` | Group access: open/allowlist/disabled |
| `WEIXIN_HOME_CHANNEL` | — | Chat ID for cron/notification output |
