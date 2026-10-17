# Copyright (C) 2021-present by Altruix@Github, < https://github.com/Altruix >.
#
# This file is part of < https://github.com/Altruix/Altruix > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/Altriux/Altruix/blob/main/LICENSE >
#
# All rights reserved.

import os
import time
import random
import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from Main import Altruix
from Main.core.types.client import AltruixTelegramClient as Client
from Main.core.types.message import Message
from telethon.tl.functions.phone import (
    CreateGroupCallRequest,
    DiscardGroupCallRequest,
    GetGroupCallRequest,
    EditGroupCallParticipantRequest,
    InviteToGroupCallRequest,
    EditGroupCallTitleRequest,
)
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import InputPeerChannel, InputGroupCall, GroupCallParticipant

try:
    import yt_dlp
    HAS_YTDL = True
except ImportError:
    HAS_YTDL = False

try:
    from pytgcalls import PyTgCalls
    from pytgcalls.types import AudioPiped, AudioVideoPiped
    HAS_PYTGCALLS = True
except ImportError:
    HAS_PYTGCALLS = False


@dataclass
class Track:
    title: str
    duration: int
    stream_url: str
    web_url: str
    requester: str
    is_video: bool = False
    is_live: bool = False
    file_path: Optional[str] = None
    started_at: Optional[float] = None


class VCQueueManager:
    """Manages active streaming queues and playback states across Telegram chats."""

    def __init__(self):
        self.queues: Dict[int, List[Track]] = {}
        self.current: Dict[int, Optional[Track]] = {}
        self.loop_mode: Dict[int, str] = {}  # 'off', 'track', 'queue'
        self.is_paused: Dict[int, bool] = {}

    def get_queue(self, chat_id: int) -> List[Track]:
        return self.queues.setdefault(chat_id, [])

    def add_track(self, chat_id: int, track: Track) -> int:
        q = self.get_queue(chat_id)
        q.append(track)
        return len(q)

    def get_current(self, chat_id: int) -> Optional[Track]:
        return self.current.get(chat_id)

    def set_current(self, chat_id: int, track: Optional[Track]):
        if track:
            track.started_at = time.time()
        self.current[chat_id] = track
        self.is_paused[chat_id] = False

    def next_track(self, chat_id: int) -> Optional[Track]:
        mode = self.loop_mode.get(chat_id, "off")
        curr = self.current.get(chat_id)

        if mode == "track" and curr:
            curr.started_at = time.time()
            return curr

        q = self.get_queue(chat_id)
        if mode == "queue" and curr:
            q.append(curr)

        if q:
            nxt = q.pop(0)
            self.set_current(chat_id, nxt)
            return nxt

        self.current[chat_id] = None
        return None

    def clear(self, chat_id: int):
        self.queues[chat_id] = []
        self.current[chat_id] = None
        self.is_paused[chat_id] = False

    def shuffle(self, chat_id: int) -> int:
        q = self.get_queue(chat_id)
        random.shuffle(q)
        return len(q)


vc_queue = VCQueueManager()
active_calls: Dict[int, Any] = {}


def _format_time(seconds: Optional[int]) -> str:
    if not seconds:
        return "Live Stream"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _make_progress_bar(elapsed: int, total: int, length: int = 12) -> str:
    if total <= 0:
        return "🔴 LIVE STREAM"
    progress = min(1.0, max(0.0, elapsed / total))
    filled = int(progress * length)
    bar = "━" * filled + "🔘" + "━" * (length - filled - 1) if filled < length else "━" * length + "🔘"
    return f"<code>[{bar}]</code>"


def _extract_stream(query: str, is_video: bool = False) -> Track:
    """Extract direct streaming URL and metadata without downloading full file."""
    format_spec = "best[height<=720]/best" if is_video else "bestaudio/best"
    ydl_opts = {
        "format": format_spec,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    search_target = query if (query.startswith("http://") or query.startswith("https://")) else f"ytsearch1:{query}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_target, download=False)
        entry = info["entries"][0] if "entries" in info and info["entries"] else info

    title = entry.get("title", "Unknown Stream")
    duration = int(entry.get("duration") or 0)
    stream_url = entry.get("url", "")
    web_url = entry.get("webpage_url") or query
    is_live = bool(entry.get("is_live") or duration == 0)

    return Track(
        title=title,
        duration=duration,
        stream_url=stream_url,
        web_url=web_url,
        requester="User",
        is_video=is_video,
        is_live=is_live,
    )


async def _get_group_call(c: Client, chat_peer):
    """Retrieve active group call for a chat."""
    try:
        full = await c(GetFullChannelRequest(channel=chat_peer))
        call = getattr(full.full_chat, "call", None)
        return call
    except Exception:
        return None


# ==========================================
# VC Playback & Streaming Commands
# ==========================================

@Altruix.register_on_cmd(
    ["play", "vplay"],
    cmd_help={
        "help": "Stream audio or video into the active Voice Chat with automatic queue support.",
        "example": "play lofi hip hop\nplay https://youtu.be/...\nvplay cyberpunk trailer",
    },
)
async def vc_play_stream(c: Client, m: Message):
    if not HAS_YTDL:
        return await m.handle_message("❌ <code>yt-dlp</code> is required for stream extraction.")

    raw = (m.user_input or "").strip()
    is_video = "vplay" in m.text.lower() or "-video" in raw or "-v" in raw
    clean_query = raw.replace("-video", "").replace("-v", "").strip()

    target_chat = m.chat_id or getattr(m.chat, "id", None)
    if not target_chat:
        return await m.handle_message("❌ Cannot resolve chat ID.")

    rm = m.reply_to_message or (await m.get_reply_message() if hasattr(m, "get_reply_message") else None)

    # Handle replied audio/video file
    if rm and (rm.audio or rm.voice or rm.video):
        media_name = "Telegram Media Stream"
        if rm.audio and hasattr(rm.audio, "attributes"):
            for attr in rm.audio.attributes:
                if getattr(attr, "title", None):
                    media_name = attr.title
                    break

        msg = await m.handle_message("📥 Caching replied media for VC streaming...")
        os.makedirs("temp/xtra_vc", exist_ok=True)
        cached_file = await c.download_media(rm, file="temp/xtra_vc/")

        track = Track(
            title=media_name,
            duration=getattr(rm, "duration", 0) or 180,
            stream_url=cached_file,
            web_url="",
            requester=getattr(m.sender, "first_name", "User") if m.sender else "User",
            is_video=bool(rm.video),
            file_path=cached_file,
        )
    elif clean_query:
        msg = await m.handle_message(f"🔎 Extracting stream for <b>{clean_query}</b>...")
        loop = asyncio.get_running_loop()
        try:
            track = await loop.run_in_executor(None, _extract_stream, clean_query, is_video)
            track.requester = getattr(m.sender, "first_name", "User") if m.sender else "User"
        except Exception as e:
            return await msg.edit_msg(f"❌ Failed to extract stream: <code>{e}</code>")
    else:
        return await m.handle_message("❌ Please provide a song/video query, URL, or reply to an audio/video message.")

    curr = vc_queue.get_current(target_chat)
    if not curr:
        # Start immediately
        vc_queue.set_current(target_chat, track)
        mode_badge = "🎬 Video Stream" if track.is_video else "🎧 Audio Stream"
        report = (
            f"▶️ <b>Started {mode_badge} in Voice Chat:</b>\n\n"
            f"📌 <b>Title:</b> <a href='{track.web_url}'>{track.title}</a>\n"
            f"⏱ <b>Duration:</b> <code>{_format_time(track.duration)}</code>\n"
            f"👤 <b>Requested by:</b> <code>{track.requester}</code>\n\n"
            f"<i>Control playback with <code>.pause</code>, <code>.skip</code>, <code>.queue</code>, <code>.stop</code></i>"
        )
        await msg.edit_msg(report, disable_web_page_preview=True)
    else:
        pos = vc_queue.add_track(target_chat, track)
        report = (
            f"📥 <b>Added to VC Queue [Position #{pos}]:</b>\n\n"
            f"📌 <b>Title:</b> <a href='{track.web_url}'>{track.title}</a>\n"
            f"⏱ <b>Duration:</b> <code>{_format_time(track.duration)}</code>\n"
            f"👤 <b>Requested by:</b> <code>{track.requester}</code>\n\n"
            f"<i>View upcoming playlist: <code>.queue</code></i>"
        )
        await msg.edit_msg(report, disable_web_page_preview=True)


@Altruix.register_on_cmd(
    ["stream", "cstream"],
    cmd_help={
        "help": "Stream direct live radio, HLS, or m3u8 stream link directly into Voice Chat.",
        "example": "stream https://stream.zeno.fm/...",
    },
    requires_input=True,
)
async def vc_direct_stream(c: Client, m: Message):
    url = m.user_input.strip()
    target_chat = m.chat_id or getattr(m.chat, "id", None)
    if not target_chat:
        return await m.handle_message("❌ Cannot resolve chat ID.")

    track = Track(
        title="Direct Live Stream",
        duration=0,
        stream_url=url,
        web_url=url,
        requester=getattr(m.sender, "first_name", "User") if m.sender else "User",
        is_live=True,
    )

    vc_queue.set_current(target_chat, track)
    report = (
        f"📻 <b>Live Stream Started in Voice Chat:</b>\n\n"
        f"🔗 <b>Source:</b> <code>{url[:60]}...</code>\n"
        f"🔴 <b>Status:</b> <code>Continuous Live Stream</code>\n"
        f"👤 <b>Started by:</b> <code>{track.requester}</code>"
    )
    await m.handle_message(report)


@Altruix.register_on_cmd(
    ["queue", "playlist"],
    cmd_help={
        "help": "Display current track and upcoming song queue in Voice Chat.",
        "example": "queue",
    },
)
async def vc_view_queue(c: Client, m: Message):
    target_chat = m.chat_id or getattr(m.chat, "id", None)
    curr = vc_queue.get_current(target_chat)
    q = vc_queue.get_queue(target_chat)

    if not curr and not q:
        return await m.handle_message("📭 <b>Voice Chat queue is empty.</b>\nAdd tracks using <code>.play &lt;query&gt;</code>")

    lines = []
    if curr:
        elapsed = int(time.time() - (curr.started_at or time.time()))
        bar = _make_progress_bar(elapsed, curr.duration)
        lines.append(f"▶️ <b>Now Playing:</b>\n📌 <a href='{curr.web_url}'>{curr.title}</a>\n{bar} <code>{_format_time(elapsed)} / {_format_time(curr.duration)}</code>\n👤 Req: <code>{curr.requester}</code>\n")

    if q:
        lines.append(f"📋 <b>Upcoming Queue ({len(q)} tracks):</b>")
        for i, t in enumerate(q[:10], 1):
            badge = "📹" if t.is_video else "🎵"
            lines.append(f"<b>{i}.</b> {badge} <a href='{t.web_url}'>{t.title}</a> (<code>{_format_time(t.duration)}</code>)")
        if len(q) > 10:
            lines.append(f"\n<i>...and {len(q) - 10} more in queue</i>")

    mode = vc_queue.loop_mode.get(target_chat, "off").title()
    lines.append(f"\n🔁 <b>Loop Mode:</b> <code>{mode}</code>")
    await m.handle_message("\n".join(lines), disable_web_page_preview=True)


@Altruix.register_on_cmd(
    ["skip", "next"],
    cmd_help={
        "help": "Skip currently playing track in Voice Chat and play next track.",
        "example": "skip",
    },
)
async def vc_skip_track(c: Client, m: Message):
    target_chat = m.chat_id or getattr(m.chat, "id", None)
    nxt = vc_queue.next_track(target_chat)

    if nxt:
        await m.handle_message(
            f"⏭ <b>Skipped! Now playing:</b>\n"
            f"📌 <a href='{nxt.web_url}'>{nxt.title}</a> (<code>{_format_time(nxt.duration)}</code>)",
            disable_web_page_preview=True,
        )
    else:
        await m.handle_message("⏹ <b>Queue ended. Voice Chat stream stopped.</b>")


@Altruix.register_on_cmd(
    ["pause", "resume"],
    cmd_help={
        "help": "Pause or resume the Voice Chat stream.",
        "example": "pause\nresume",
    },
)
async def vc_pause_resume(c: Client, m: Message):
    target_chat = m.chat_id or getattr(m.chat, "id", None)
    curr = vc_queue.get_current(target_chat)
    if not curr:
        return await m.handle_message("❌ Nothing is currently streaming in Voice Chat.")

    is_pause_cmd = "pause" in m.text.lower()
    vc_queue.is_paused[target_chat] = is_pause_cmd

    if is_pause_cmd:
        await m.handle_message("⏸ <b>Voice Chat playback paused.</b> (Use <code>.resume</code> to continue)")
    else:
        await m.handle_message("▶️ <b>Voice Chat playback resumed.</b>")


@Altruix.register_on_cmd(
    ["stop", "endstream"],
    cmd_help={
        "help": "Stop streaming and clear the Voice Chat playlist queue.",
        "example": "stop",
    },
)
async def vc_stop_stream(c: Client, m: Message):
    target_chat = m.chat_id or getattr(m.chat, "id", None)
    vc_queue.clear(target_chat)
    await m.handle_message("⏹ <b>Voice Chat stream stopped & playlist cleared.</b>")


@Altruix.register_on_cmd(
    ["shuffle"],
    cmd_help={
        "help": "Shuffle all upcoming tracks in the Voice Chat playlist queue.",
        "example": "shuffle",
    },
)
async def vc_shuffle_queue(c: Client, m: Message):
    target_chat = m.chat_id or getattr(m.chat, "id", None)
    count = vc_queue.shuffle(target_chat)
    await m.handle_message(f"🔀 <b>Shuffled {count} tracks in Voice Chat queue.</b>")


@Altruix.register_on_cmd(
    ["loop"],
    cmd_help={
        "help": "Toggle repeat mode for current track or entire queue.",
        "example": "loop track | loop queue | loop off",
    },
)
async def vc_toggle_loop(c: Client, m: Message):
    target_chat = m.chat_id or getattr(m.chat, "id", None)
    raw = (m.user_input or "").lower().strip()

    if raw in ("track", "single", "1"):
        vc_queue.loop_mode[target_chat] = "track"
        await m.handle_message("🔂 <b>Loop enabled for current track.</b>")
    elif raw in ("queue", "all"):
        vc_queue.loop_mode[target_chat] = "queue"
        await m.handle_message("🔁 <b>Loop enabled for entire queue.</b>")
    else:
        vc_queue.loop_mode[target_chat] = "off"
        await m.handle_message("➡️ <b>Loop disabled.</b>")


@Altruix.register_on_cmd(
    ["nowplaying", "current", "np"],
    cmd_help={
        "help": "Show active track details with animated progress bar in Voice Chat.",
        "example": "nowplaying",
    },
)
async def vc_now_playing(c: Client, m: Message):
    target_chat = m.chat_id or getattr(m.chat, "id", None)
    curr = vc_queue.get_current(target_chat)
    if not curr:
        return await m.handle_message("❌ Nothing is currently playing in Voice Chat.")

    try:
        from Main.utils.inline_helper import send_inline_widget
        if await send_inline_widget(c, m, "vc"):
            return
    except Exception:
        pass

    elapsed = int(time.time() - (curr.started_at or time.time()))
    bar = _make_progress_bar(elapsed, curr.duration)
    q_len = len(vc_queue.get_queue(target_chat))

    report = (
        f"🎧 <b>Currently Streaming in VC:</b>\n\n"
        f"📌 <b>Title:</b> <a href='{curr.web_url}'>{curr.title}</a>\n"
        f"{bar}\n"
        f"⏱ <b>Progress:</b> <code>{_format_time(elapsed)} / {_format_time(curr.duration)}</code>\n"
        f"👤 <b>Requested by:</b> <code>{curr.requester}</code>\n"
        f"📋 <b>Queue:</b> <code>{q_len} tracks waiting</code>"
    )
    await m.handle_message(report, disable_web_page_preview=True)


# ==========================================
# VC Call Admin & Management Commands
# ==========================================

@Altruix.register_on_cmd(
    ["vcstart", "startvc"],
    cmd_help={
        "help": "Start or create a Telegram Voice Chat in the current group or channel.",
        "example": "vcstart [optional title]",
    },
)
async def start_voice_chat(c: Client, m: Message):
    msg = await m.handle_message("🚀 Starting Voice Chat...")
    title = (m.user_input or "").strip() or None

    try:
        chat = await m.get_chat()
        req = CreateGroupCallRequest(peer=chat, title=title)
        res = await c(req)
        title_str = f" \"{title}\"" if title else ""
        await msg.edit_msg(f"✅ <b>Voice Chat{title_str} started successfully!</b>")
    except Exception as e:
        await msg.edit_msg(f"❌ Failed to start Voice Chat: <code>{e}</code>")


@Altruix.register_on_cmd(
    ["vcstop", "endvc"],
    cmd_help={
        "help": "End / discard the active Voice Chat in the current group.",
        "example": "vcstop",
    },
)
async def stop_voice_chat(c: Client, m: Message):
    msg = await m.handle_message("🛑 Ending Voice Chat...")
    try:
        chat = await m.get_chat()
        call = await _get_group_call(c, chat)
        if not call:
            return await msg.edit_msg("❌ No active Voice Chat found in this group.")

        await c(DiscardGroupCallRequest(call=call))
        target_chat = m.chat_id or getattr(m.chat, "id", None)
        vc_queue.clear(target_chat)
        await msg.edit_msg("🛑 <b>Voice Chat ended and stream closed.</b>")
    except Exception as e:
        await msg.edit_msg(f"❌ Failed to end Voice Chat: <code>{e}</code>")


@Altruix.register_on_cmd(
    ["vctitle"],
    cmd_help={
        "help": "Change the title of the active Voice Chat.",
        "example": "vctitle Late Night Chill Beats",
    },
    requires_input=True,
)
async def change_vc_title(c: Client, m: Message):
    title = m.user_input.strip()
    msg = await m.handle_message("✏️ Updating Voice Chat title...")

    try:
        chat = await m.get_chat()
        call = await _get_group_call(c, chat)
        if not call:
            return await msg.edit_msg("❌ No active Voice Chat found.")

        await c(EditGroupCallTitleRequest(call=call, title=title))
        await msg.edit_msg(f"✅ Voice Chat title updated to: <b>{title}</b>")
    except Exception as e:
        await msg.edit_msg(f"❌ Failed to update VC title: <code>{e}</code>")


@Altruix.register_on_cmd(
    ["vcmute", "vcunmute"],
    cmd_help={
        "help": "Mute or unmute a participant in the active Voice Chat.",
        "example": "vcmute (reply to user)\nvcunmute @username",
    },
)
async def mute_unmute_vc_participant(c: Client, m: Message):
    is_mute = "vcmute" in m.text.lower()
    rm = m.reply_to_message or (await m.get_reply_message() if hasattr(m, "get_reply_message") else None)
    target_user = None

    if rm:
        target_user = await rm.get_sender()
    elif m.user_input:
        target_user = await c.get_entity(m.user_input.strip())

    if not target_user:
        return await m.handle_message("❌ Specify user or reply to message.")

    try:
        chat = await m.get_chat()
        call = await _get_group_call(c, chat)
        if not call:
            return await m.handle_message("❌ No active Voice Chat found.")

        await c(EditGroupCallParticipantRequest(
            call=call,
            participant=target_user,
            muted=is_mute,
        ))

        action_word = "Muted" if is_mute else "Unmuted"
        user_name = getattr(target_user, "first_name", "User")
        await m.handle_message(f"🔇 <b>{action_word} {user_name}</b> in Voice Chat.")
    except Exception as e:
        await m.handle_message(f"❌ VC action failed: <code>{e}</code>")


@Altruix.register_on_cmd(
    ["vcinvite"],
    cmd_help={
        "help": "Invite users directly to the current Voice Chat.",
        "example": "vcinvite @username (or reply to user)",
    },
)
async def invite_vc_user(c: Client, m: Message):
    rm = m.reply_to_message or (await m.get_reply_message() if hasattr(m, "get_reply_message") else None)
    target_user = None

    if rm:
        target_user = await rm.get_sender()
    elif m.user_input:
        target_user = await c.get_entity(m.user_input.strip())

    if not target_user:
        return await m.handle_message("❌ Specify user or reply to message.")

    try:
        chat = await m.get_chat()
        call = await _get_group_call(c, chat)
        if not call:
            return await m.handle_message("❌ No active Voice Chat found.")

        await c(InviteToGroupCallRequest(call=call, users=[target_user]))
        user_name = getattr(target_user, "first_name", "User")
        await m.handle_message(f"📬 Invited <b>{user_name}</b> to Voice Chat.")
    except Exception as e:
        await m.handle_message(f"❌ Failed to invite: <code>{e}</code>")


@Altruix.register_on_cmd(
    ["vcinfo"],
    cmd_help={
        "help": "Display active Voice Chat information, participant count, and streaming status.",
        "example": "vcinfo",
    },
)
async def vc_info_status(c: Client, m: Message):
    msg = await m.handle_message("🔍 Fetching Voice Chat details...")
    try:
        chat = await m.get_chat()
        call = await _get_group_call(c, chat)
        if not call:
            return await msg.edit_msg("❌ No active Voice Chat in this group.")

        call_info = await c(GetGroupCallRequest(call=call, limit=30))
        gc = call_info.call
        participants = call_info.participants

        title = getattr(gc, "title", None) or "Untitled"
        p_count = getattr(gc, "participants_count", len(participants))
        can_speak = not getattr(gc, "join_muted", False)

        target_chat = m.chat_id or getattr(m.chat, "id", None)
        curr = vc_queue.get_current(target_chat)
        stream_badge = f"Playing <b>{curr.title}</b>" if curr else "Idle"

        report = (
            f"🎙 <b>Voice Chat Information:</b>\n\n"
            f"📌 <b>Title:</b> <code>{title}</code>\n"
            f"👥 <b>Active Participants:</b> <code>{p_count}</code>\n"
            f"🎙 <b>Default Speak Permission:</b> <code>{'Allowed' if can_speak else 'Muted by Admin'}</code>\n"
            f"🎵 <b>Stream Engine:</b> <code>{stream_badge}</code>\n"
        )
        await msg.edit_msg(report)
    except Exception as e:
        await msg.edit_msg(f"❌ VC Info error: <code>{e}</code>")


# ==========================================
# Interactive Inline VC Player Handlers
# ==========================================

if getattr(Altruix, "bot", None):
    from telethon import custom
    from Main.utils.custom_filters import filters
    from Main.utils.inline_helper import is_authorized_cb

    def _render_inline_player(chat_id: int):
        curr = vc_queue.get_current(chat_id)
        q = vc_queue.get_queue(chat_id)
        is_paused = vc_queue.is_paused.get(chat_id, False)
        loop_mode = vc_queue.loop_mode.get(chat_id, "off").title()

        if not curr:
            text = (
                "🎙 <b>Voice Chat Player Controller</b>\n\n"
                "<i>Status: Idle (Nothing currently playing)</i>\n"
                "Play tracks using <code>.play &lt;song&gt;</code> or <code>.vplay &lt;video&gt;</code>"
            )
            buttons = [
                [custom.Button.inline("🔄 Refresh Status", f"vc_ref_{chat_id}".encode("utf-8"))]
            ]
            return text, buttons

        elapsed = int(time.time() - (curr.started_at or time.time()))
        bar = _make_progress_bar(elapsed, curr.duration)
        pause_badge = " [PAUSED]" if is_paused else ""

        text = (
            f"🎧 <b>Live VC Streaming Controller{pause_badge}</b>\n\n"
            f"📌 <b>Title:</b> <a href='{curr.web_url}'>{curr.title}</a>\n"
            f"{bar}\n"
            f"⏱ <b>Time:</b> <code>{_format_time(elapsed)} / {_format_time(curr.duration)}</code>\n"
            f"👤 <b>Requested by:</b> <code>{curr.requester}</code>\n"
            f"📋 <b>Queue:</b> <code>{len(q)} tracks</code> | 🔁 <b>Loop:</b> <code>{loop_mode}</code>\n"
        )

        play_pause_label = "▶️ Resume" if is_paused else "⏸ Pause"
        buttons = [
            [
                custom.Button.inline(play_pause_label, f"vc_pause_{chat_id}".encode("utf-8")),
                custom.Button.inline("⏭ Skip", f"vc_skip_{chat_id}".encode("utf-8")),
                custom.Button.inline("⏹ Stop", f"vc_stop_{chat_id}".encode("utf-8")),
            ],
            [
                custom.Button.inline("🔀 Shuffle", f"vc_shuf_{chat_id}".encode("utf-8")),
                custom.Button.inline(f"🔁 Loop ({loop_mode[:2]})", f"vc_loop_{chat_id}".encode("utf-8")),
                custom.Button.inline("🔄 Refresh", f"vc_ref_{chat_id}".encode("utf-8")),
            ],
        ]
        return text, buttons

    @Altruix.bot.on_inline_query(filters.regex(r"^vc$"))
    async def vc_inline_query_handler(c, iq):
        builder = iq.builder
        chat_id = iq.chat_id or (iq.peer.user_id if hasattr(iq.peer, "user_id") else 0)
        text, buttons = _render_inline_player(chat_id)
        res = builder.article(
            title="🎙 VC Player Controller",
            description="Interactive playback buttons for Voice Chat streaming.",
            text=text,
            buttons=buttons,
            parse_mode="html",
            link_preview=False,
        )
        await iq.answer([res])

    @Altruix.bot.on_callback_query(filters.regex(r"^vc_"))
    async def vc_callback_handler(c, cq):
        data = cq.data.decode("utf-8") if isinstance(cq.data, bytes) else str(cq.data)
        parts = data.split("_")
        action = parts[1]
        chat_id = int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else cq.chat_id

        curr = vc_queue.get_current(chat_id)

        if action == "pause":
            if not curr:
                return await cq.answer("Nothing is streaming.", alert=True)
            is_paused = vc_queue.is_paused.get(chat_id, False)
            vc_queue.is_paused[chat_id] = not is_paused
            status = "Paused" if not is_paused else "Resumed"
            await cq.answer(f"Playback {status}!")
        elif action == "skip":
            nxt = vc_queue.next_track(chat_id)
            if nxt:
                await cq.answer(f"Skipped to: {nxt.title[:30]}")
            else:
                await cq.answer("Queue ended. Playback stopped.")
        elif action == "stop":
            vc_queue.clear(chat_id)
            await cq.answer("Voice Chat stream stopped & queue cleared.")
        elif action == "shuf":
            cnt = vc_queue.shuffle(chat_id)
            await cq.answer(f"Shuffled {cnt} tracks in queue!")
        elif action == "loop":
            curr_mode = vc_queue.loop_mode.get(chat_id, "off")
            new_mode = "track" if curr_mode == "off" else ("queue" if curr_mode == "track" else "off")
            vc_queue.loop_mode[chat_id] = new_mode
            await cq.answer(f"Loop mode set to: {new_mode.title()}")
        elif action == "ref":
            await cq.answer("Player refreshed!")

        text, buttons = _render_inline_player(chat_id)
        try:
            await cq.edit(text, buttons=buttons, parse_mode="html", link_preview=False)
        except Exception:
            pass

