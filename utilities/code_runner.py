# Copyright (C) 2021-present by Altruix@Github, < https://github.com/Altruix >.
#
# This file is part of < https://github.com/Altruix/Altruix > project,
# and is released under the "GNU v3.0 License Agreement".

import time
import html
import httpx
from typing import Optional, Dict

from Main import Altruix
from Main.core.types.client import AltruixTelegramClient as Client
from Main.core.types.message import Message

PISTON_API_URL = "https://emkc.org/api/v2/piston/execute"

LANG_ALIASES: Dict[str, str] = {
    "py": "python",
    "python": "python",
    "python3": "python",
    "js": "javascript",
    "javascript": "javascript",
    "node": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "c++": "c++",
    "cpp": "c++",
    "c": "c",
    "rs": "rust",
    "rust": "rust",
    "go": "go",
    "golang": "go",
    "java": "java",
    "sh": "bash",
    "bash": "bash",
    "php": "php",
    "rb": "ruby",
    "ruby": "ruby",
}


@Altruix.register_on_cmd(
    ["run", "coderun", "piston", "execode"],
    cmd_help={
        "help": "Execute code in an isolated sandbox across 30+ programming languages via Piston API.",
        "example": "run py print(sum(range(100)))\nrun js console.log(Math.PI)\nrun c #include <stdio.h>\\nint main() { printf(\"Hello!\"); return 0; }",
    },
)
async def code_runner_cmd(c: Client, m: Message):
    reply = m.reply_to_message or (await m.get_reply_message()) if hasattr(m, "get_reply_message") else None
    raw = (m.user_input or "").strip()

    lang = "python"
    code = ""

    if reply and (reply.text or reply.raw_text):
        rep_text = reply.text or reply.raw_text
        if raw in LANG_ALIASES:
            lang = LANG_ALIASES[raw]
            code = rep_text
        else:
            code = rep_text
    elif raw:
        parts = raw.split(None, 1)
        first_token = parts[0].lower()
        if first_token in LANG_ALIASES and len(parts) > 1:
            lang = LANG_ALIASES[first_token]
            code = parts[1].strip()
        else:
            code = raw
    else:
        return await m.handle_message(
            "⚠️ <b>Usage:</b> <code>.run &lt;language&gt; &lt;code&gt;</code> or reply to a code message.\n"
            "<b>Supported:</b> <code>python</code>, <code>javascript</code>, <code>c++</code>, <code>rust</code>, <code>go</code>, <code>bash</code>, <code>java</code>"
        )

    # Strip markdown code blocks if wrapped
    if code.startswith("```") and code.endswith("```"):
        lines = code.splitlines()
        first_line = lines[0].replace("```", "").strip().lower()
        if first_line in LANG_ALIASES:
            lang = LANG_ALIASES[first_line]
        code = "\n".join(lines[1:-1])

    msg = await m.handle_message(f"⚡ Running <b>{lang.title()}</b> sandbox...")
    start_time = time.perf_counter()

    payload = {
        "language": lang,
        "version": "*",
        "files": [{"name": f"main.{lang}", "content": code}],
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(PISTON_API_URL, json=payload)
            if resp.status_code != 200:
                return await msg.edit_msg(f"❌ Sandbox execution error (HTTP {resp.status_code}):\n<code>{resp.text}</code>")
            data = resp.json()

        elapsed = (time.perf_counter() - start_time) * 1000
        run_res = data.get("run", {})
        stdout = (run_res.get("stdout") or "").strip()
        stderr = (run_res.get("stderr") or "").strip()
        exit_code = run_res.get("code", 0)
        ver = data.get("version", "")

        status_badge = "🟢 Success" if exit_code == 0 else f"🔴 Exit Code: {exit_code}"

        output = stdout if stdout else (stderr if stderr else "<i>(No output returned)</i>")
        if len(output) > 3000:
            output = output[:3000] + "\n... [Truncated]"

        report = (
            f"⚡ <b>Execution Result:</b> {status_badge}\n"
            f"💻 <b>Language:</b> <code>{lang} (v{ver})</code> | ⏱ <b>Time:</b> <code>{elapsed:.1f} ms</code>\n\n"
            f"<b>Output:</b>\n<pre>{html.escape(output)}</pre>"
        )

        user_id = m.sender_id or 0
        token = str(int(time.time() * 1000))[-8:]
        _piston_cache[token] = (report, user_id)

        if "-basic" not in m.user_args and "-text" not in m.user_args:
            try:
                from Main.utils.inline_helper import send_inline_widget
                if await send_inline_widget(c, m, f"piston:{token}"):
                    with suppress_error(msg="deleting status message"):
                        await msg.delete()
                    return
            except Exception:
                pass

        await msg.edit_msg(report)

    except Exception as e:
        await msg.edit_msg(f"❌ Execution error: <code>{e}</code>")


# ==========================================
# Interactive Inline Piston Code Runner
# ==========================================

_piston_cache = {}

if getattr(Altruix, "bot", None):
    import re
    from telethon import custom
    from Main.utils.custom_filters import filters
    from Main.utils.inline_helper import is_owner
    from Main.utils.suppress import suppress_error

    @Altruix.bot.on_inline_query(filters.regex(r"^piston:(\w+)"))
    async def piston_inline_query_handler(c, iq):
        m = re.match(r"^piston:(\w+)", iq.text)
        token = m.group(1) if m else ""
        cached = _piston_cache.get(token)
        if not cached:
            return

        report, user_id = cached
        buttons = [
            [
                custom.Button.inline("🗑 Delete Output", f"piston_del:{user_id}".encode("utf-8")),
            ]
        ]
        builder = iq.builder
        res = builder.article(
            title="⚡ Code Sandbox Output",
            description="Sandbox execution result with delete button.",
            text=report,
            buttons=buttons,
            parse_mode="html",
        )
        await iq.answer([res], cache_time=0)

    @Altruix.bot.on_callback_query(filters.regex(r"^piston_del:(\d+)"))
    async def piston_callback_handler(c, cq):
        m = re.match(r"^piston_del:(\d+)", cq.data.decode("utf-8") if isinstance(cq.data, bytes) else str(cq.data))
        owner_id = int(m.group(1)) if m else 0
        if cq.sender_id != owner_id and not is_owner(cq.sender_id):
            return await cq.answer("⛔ Access denied: Only the user who ran this code can delete its output.", alert=True)

        try:
            await cq.delete()
        except (TypeError, Exception):
            try:
                await cq.edit("🗑 <i>Output deleted.</i>", buttons=None, parse_mode="html")
            except Exception:
                pass

