# Copyright (C) 2021-present by Altruix@Github, < https://github.com/Altruix >.
#
# This file is part of < https://github.com/Altruix/Altruix > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/Altriux/Altruix/blob/main/LICENSE >
#
# All rights reserved.

import urllib.parse
from typing import Optional, Tuple
from Main import Altruix
from Main.core.types.client import AltruixTelegramClient as Client
from Main.core.types.message import Message

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


async def _fetch_translation(text: str, target_lang: str, source_lang: str = "auto") -> Tuple[Optional[str], str]:
    """Translate text using standard HTTP translation endpoint."""
    encoded_text = urllib.parse.quote(text)
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q={encoded_text}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if res.status_code == 200:
            data = res.json()
            translated_chunks = []
            detected_src = source_lang
            if data and isinstance(data, list):
                if len(data) > 0 and isinstance(data[0], list):
                    for part in data[0]:
                        if part and len(part) > 0 and part[0]:
                            translated_chunks.append(part[0])
                if len(data) > 2 and isinstance(data[2], str):
                    detected_src = data[2]
            return "".join(translated_chunks), detected_src
    return None, source_lang


@Altruix.register_on_cmd(
    ["trans", "translate", "tl"],
    cmd_help={
        "help": "Translate text or replied message to any target language code (e.g. en, es, fr, de, hi, ja, ru).",
        "example": "trans es Hello friend or trans ja (replying to message)",
    },
)
async def translate_message(c: Client, m: Message):
    if not HAS_HTTPX:
        return await m.handle_message("❌ <code>httpx</code> is required for translation.")

    raw = (m.user_input or "").strip()
    target_lang = "en"
    text_to_translate = ""

    rm = m.reply_to_message or (await m.get_reply_message() if hasattr(m, "get_reply_message") else None)

    if raw:
        parts = raw.split(" ", 1)
        if len(parts[0]) in (2, 3) and parts[0].isalpha():
            target_lang = parts[0].lower()
            if len(parts) > 1:
                text_to_translate = parts[1].strip()
        else:
            text_to_translate = raw

    if not text_to_translate and rm:
        text_to_translate = rm.text or rm.caption or ""

    if not text_to_translate:
        return await m.handle_message("❌ Please provide text to translate or reply to a text message.")

    msg = await m.handle_message(f"🌐 Translating to <b>{target_lang.upper()}</b>...")

    try:
        translated_text, src = await _fetch_translation(text_to_translate, target_lang)
        if not translated_text:
            return await msg.edit_msg("❌ Translation failed or returned empty response.")

        report = (
            f"🌐 <b>Translation ({src.upper()} ➔ {target_lang.upper()})</b>\n\n"
            f"{translated_text}"
        )
        await msg.edit_msg(report)
    except Exception as e:
        await msg.edit_msg(f"❌ Error during translation: <code>{e}</code>")
