"""zhuangtai plugin: /zhuangtai runtime status."""

from __future__ import annotations


def register(ctx):
    """Register the /zhuangtai slash command and hermes zhuangtai CLI command."""
    from .status import build_status_text

    def _handle(raw_args: str = "") -> str:
        raw = (raw_args or "").strip().lower()
        if raw in {"help", "-h", "--help", "?"}:
            return "用法：/zhuangtai\n显示网络/IP/代理、归属地、当前模型、账号用量、等效 API 额度和 Codex 降智预警。只读，不输出 token/API key。"
        return build_status_text(ctx)

    def _setup_argparse(subparser):
        subparser.set_defaults(func=_handle_cli)

    def _handle_cli(args):
        del args
        print(build_status_text(ctx))

    ctx.register_command(
        "zhuangtai",
        handler=_handle,
        description="显示运行状态、等效 API 额度和 Codex 降智预警",
    )
    ctx.register_cli_command(
        name="zhuangtai",
        help="显示运行状态、等效 API 额度和 Codex 降智预警",
        setup_fn=_setup_argparse,
        handler_fn=_handle_cli,
        description="显示运行状态、等效 API 额度和 Codex 降智预警",
    )
