---
sidebar_position: 17
title: "OAuth over SSH / Remote Hosts"
---

# OAuth over SSH / Remote Hosts


This works perfectly when Hermes and your browser are on the same machine. It breaks the moment they aren't: your laptop's browser tries to reach `127.0.0.1` on **your laptop**, but the listener is bound to `127.0.0.1` on **the remote server**.

The fix is a one-line SSH local-forward. For MCP servers on an interactive terminal, you can often paste the redirect URL back instead (no tunnel).

**xAI Grok OAuth (`xai-oauth`) uses OAuth device code**, not a loopback callback — open the printed verification URL in any browser and Hermes polls until approval. No SSH tunnel is required. See [xAI Grok OAuth](./xai-grok-oauth.md).

## MCP Servers

Remote MCP servers (Linear, Sentry, Atlassian, Asana, Figma, etc.) use the same loopback redirect flow. Hermes auto-picks a free port per server and prints the authorize URL when the OAuth flow kicks off — either at startup (when a new server appears in `mcp_servers:`) or when you run `hermes mcp login <server>`.

You have two ways to complete it from a remote host:

**Option 1 — paste the redirect URL back (no setup, works anywhere).** On an interactive terminal, Hermes prompts you to paste the redirect URL alongside running the local listener. After approving in your browser, the redirect to `http://127.0.0.1:<port>/callback` will show a connection error — that's expected. Copy the **full URL from the browser's address bar** and paste it at the Hermes prompt:

```
  MCP OAuth: authorization required.
  Open this URL in your browser:

    https://mcp.linear.app/authorize?response_type=code&...

  Or paste the redirect URL here (or the ?code=...&state=... portion) and press Enter:
> https://mcp.linear.app/callback?code=abc123&state=xyz
  Got authorization code from paste — completing flow.
```

A bare `?code=...&state=...` query string is accepted too. This works for any MCP server with `auth: oauth` and requires no SSH config changes.


```bash
ssh -N -L <port>:127.0.0.1:<port> user@remote-host
```

Then open the authorize URL in your browser as normal; the redirect tunnels through and the listener picks it up. Use this when you need the flow to complete unattended (e.g. scripted re-auth where you can't paste interactively).

**Pitfall — the 30s config-reload race.** If you edit `~/.hermes/config.yaml` to add an OAuth MCP server from inside a running Hermes session, the CLI auto-reloads MCP connections with a 30s timeout. That's not enough time to complete an interactive OAuth flow, and the reload will give up. Use `hermes mcp login <server>` from a fresh terminal instead — it has no such cap and waits the full 5 min for you to paste back.




### 1. Start the tunnel from your local machine

```bash
```

`-N` means "don't open a remote shell, just hold the tunnel open." Keep this terminal running for the duration of the login.

### 2. In a separate SSH session, run the auth command

```bash
ssh user@remote-host
```

Hermes detects the SSH session, skips the browser auto-open, and prints an authorize URL plus a `Waiting for callback on http://127.0.0.1:<port>/callback` line.

### 3. Open the URL in your local browser

Copy the authorize URL from the remote terminal and paste it into the browser on your laptop. Approve the consent screen. The auth server redirects to `http://127.0.0.1:<port>/callback`. Your browser hits the tunnel, the request is forwarded to the remote listener, and Hermes prints `Login successful!`.

You can tear down the tunnel (Ctrl+C in the first terminal) once you see the success line.


If you reach Hermes through a bastion / jump host, use SSH's built-in `-J` (ProxyJump):

```bash
```


For older OpenSSH that doesn't support `-J`, the long form is:

```bash
ssh -N \
    -o "ProxyCommand=ssh -W %h:%p jump-user@jump-host" \
    user@final-host
```

## Mosh, tmux, ssh ControlMaster

The tunnel is a property of the underlying SSH connection. If you're running Hermes inside `tmux` over a mosh session, the mosh roaming doesn't carry the `-L` forwarding. Open a *separate* plain SSH session **only** for the `-L` tunnel — that's the connection that has to stay alive during the auth flow. Your interactive mosh/tmux session can keep running Hermes normally.

If you use `ssh -o ControlMaster=auto`, port forwards on a multiplexed connection share the master's lifetime. Restart the master if the tunnel doesn't come up:

```bash
ssh -O exit user@remote-host
```

## Troubleshooting


Something on your laptop is already using that port. Either the previous tunnel didn't shut down cleanly, or a local Hermes is also listening on it. Find and kill the offender:

```bash
# macOS / Linux
kill <PID>
```

Then retry the `ssh -L` command.

### Authorization timed out waiting for the local callback

The redirect never made it back to the remote listener. Check the tunnel is still alive (`ssh -N` doesn't show output, so look at the terminal you started it from), confirm you used the port from the latest `Waiting for callback on ...` line (Hermes may auto-bump if the preferred port is busy), restart the tunnel if needed, and re-run the auth command.

### Tokens land in the wrong `~/.hermes`

The tokens are written under the Linux user that ran `hermes auth add ...`. If your gateway / systemd service runs as a different user (e.g. `root` or a dedicated `hermes` user), authenticate as **that** user so the tokens land in their `~/.hermes/auth.json`. `sudo -u hermes -i` or equivalent.

## See Also

- [xAI Grok OAuth](./xai-grok-oauth.md) — device code; no SSH tunnel
- [Native MCP client (OAuth section)](../user-guide/features/mcp.md#oauth-authenticated-http-servers)
- [SSH `-J` / ProxyJump (man page)](https://man.openbsd.org/ssh#J)
