# Copyright (C) 2021-present by Altruix@Github, < https://github.com/Altruix >.
#
# This file is part of < https://github.com/Altruix/Altruix > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/Altriux/Altruix/blob/main/LICENSE >
#
# All rights reserved.

import os
import re
import asyncio
import datetime
from typing import Optional, Dict, Any, List

from Main import Altruix
from Main.core.types.client import AltruixTelegramClient as Client
from Main.core.types.message import Message

try:
    import yt_dlp
    HAS_YTDL = True
except ImportError:
    HAS_YTDL = False

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    import shutil
    FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"


def _format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "Live / Unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _format_count(num: Optional[int]) -> str:
    if not num:
        return "0"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(num)


def _get_ffmpeg_cmd() -> Optional[str]:
    import shutil
    path = shutil.which("ffmpeg")
    if path:
        return path
    if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
        return FFMPEG_PATH
    return None


@Altruix.register_on_cmd(
    ["ytdl", "ytvideo", "ytv"],
    cmd_help={
        "help": "Download high quality videos from YouTube and supported web platforms with streaming metadata.",
        "example": "ytdl https://youtu.be/... -720p\nytdl lofi hip hop -480p",
    },
    requires_input=True,
)
async def youtube_download_video(c: Client, m: Message):
    if not HAS_YTDL:
        return await m.handle_message("❌ <code>yt-dlp</code> is required. Install via <code>pip install yt-dlp</code>.")

    raw = m.user_input.strip()
    quality = "720"
    for q in ["1080", "720", "480", "360"]:
        if f"-{q}p" in raw or f"-{q}" in raw:
            quality = q
            raw = raw.replace(f"-{q}p", "").replace(f"-{q}", "").strip()
            break

    query = raw.strip()
    if not query:
        return await m.handle_message("❌ Please provide a video URL or search query.")

    msg = await m.handle_message(f"🔍 Searching & extracting video (Quality: <b>{quality}p</b>)...")
    out_dir = os.path.join("temp", "xtra_ytdl")
    os.makedirs(out_dir, exist_ok=True)
    out_tmpl = os.path.join(out_dir, "%(id)s.%(ext)s")

    format_spec = f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}]/best"

    ydl_opts = {
        "format": format_spec,
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "writethumbnail": True,
    }

    ffmpeg_bin = _get_ffmpeg_cmd()
    if ffmpeg_bin:
        ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_bin) if os.path.isfile(ffmpeg_bin) else ffmpeg_bin

    try:
        loop = asyncio.get_running_loop()

        def _extract_and_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_target = query if query.startswith("http://") or query.startswith("https://") else f"ytsearch1:{query}"
                info = ydl.extract_info(search_target, download=True)
                if "entries" in info and info["entries"]:
                    return info["entries"][0]
                return info

        await msg.edit_msg(f"⬇️ Downloading video: <code>{query}</code>...")
        entry = await loop.run_in_executor(None, _extract_and_download)

        vid_id = entry.get("id")
        title = entry.get("title", "Video")
        duration = int(entry.get("duration") or 0)
        channel = entry.get("uploader") or entry.get("channel", "YouTube")
        web_url = entry.get("webpage_url") or f"https://youtu.be/{vid_id}"

        # Locate downloaded video file
        video_file = None
        thumb_file = None
        for fn in os.listdir(out_dir):
            if fn.startswith(vid_id):
                fp = os.path.join(out_dir, fn)
                if fn.endswith((".mp4", ".mkv", ".webm")):
                    video_file = fp
                elif fn.endswith((".jpg", ".jpeg", ".webp", ".png")):
                    thumb_file = fp

        if not video_file or not os.path.exists(video_file):
            return await msg.edit_msg("❌ Video download failed: file not found on disk.")

        file_size_mb = os.path.getsize(video_file) / (1024 * 1024)
        if file_size_mb > 2000:
            return await msg.edit_msg(f"❌ File size exceeds Telegram 2GB limit ({file_size_mb:.1f} MB).")

        await msg.edit_msg(f"⬆️ Uploading <b>{title}</b> ({file_size_mb:.1f} MB)...")

        caption = (
            f"🎬 <b><a href='{web_url}'>{title}</a></b>\n"
            f"⏱ <b>Duration:</b> <code>{_format_duration(duration)}</code> | <b>Channel:</b> <code>{channel}</code>"
        )

        target_chat = m.chat_id or getattr(m.chat, "id", None)
        await c.send_file(
            target_chat,
            video_file,
            caption=caption,
            thumb=thumb_file if thumb_file and os.path.exists(thumb_file) else None,
            supports_streaming=True,
            reply_to=m.id,
        )

        await msg.delete()

    except Exception as e:
        await msg.edit_msg(f"❌ Video error: <code>{e}</code>")
    finally:
        # Cleanup
        try:
            if 'vid_id' in locals():
                for fn in os.listdir(out_dir):
                    if fn.startswith(vid_id):
                        try:
                            os.remove(os.path.join(out_dir, fn))
                        except Exception:
                            pass
        except Exception:
            pass


@Altruix.register_on_cmd(
    ["ytmp3", "ytaudio", "song", "music"],
    cmd_help={
        "help": "Download high bitrate audio / song with embedded tags, thumbnail, and performer information.",
        "example": "ytmp3 https://youtu.be/...\nsong Bohemian Rhapsody",
    },
    requires_input=True,
)
async def youtube_download_audio(c: Client, m: Message):
    if not HAS_YTDL:
        return await m.handle_message("❌ <code>yt-dlp</code> is required. Install via <code>pip install yt-dlp</code>.")

    query = m.user_input.strip()
    if not query:
        return await m.handle_message("❌ Please provide song name or YouTube link.")

    msg = await m.handle_message(f"🎵 Searching song <b>{query}</b>...")
    out_dir = os.path.join("temp", "xtra_ytdl")
    os.makedirs(out_dir, exist_ok=True)
    out_tmpl = os.path.join(out_dir, "%(id)s.%(ext)s")

    ffmpeg_bin = _get_ffmpeg_cmd()
    postprocessors = [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "320",
    }] if ffmpeg_bin else []

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "writethumbnail": True,
        "postprocessors": postprocessors,
    }

    if ffmpeg_bin:
        ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_bin) if os.path.isfile(ffmpeg_bin) else ffmpeg_bin

    try:
        loop = asyncio.get_running_loop()

        def _extract_and_download_audio():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_target = query if query.startswith("http://") or query.startswith("https://") else f"ytsearch1:{query}"
                info = ydl.extract_info(search_target, download=True)
                if "entries" in info and info["entries"]:
                    return info["entries"][0]
                return info

        await msg.edit_msg(f"⬇️ Downloading audio track for <code>{query}</code>...")
        entry = await loop.run_in_executor(None, _extract_and_download_audio)

        vid_id = entry.get("id")
        title = entry.get("title", "Audio Track")
        duration = int(entry.get("duration") or 0)
        performer = entry.get("artist") or entry.get("uploader") or entry.get("channel", "Unknown Artist")
        web_url = entry.get("webpage_url") or f"https://youtu.be/{vid_id}"

        # Find downloaded audio and thumbnail
        audio_file = None
        thumb_file = None
        for fn in os.listdir(out_dir):
            if fn.startswith(vid_id):
                fp = os.path.join(out_dir, fn)
                if fn.endswith((".mp3", ".m4a", ".opus", ".ogg")):
                    audio_file = fp
                elif fn.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    thumb_file = fp

        if not audio_file or not os.path.exists(audio_file):
            return await msg.edit_msg("❌ Audio extraction failed: file not found on disk.")

        file_size_mb = os.path.getsize(audio_file) / (1024 * 1024)
        await msg.edit_msg(f"⬆️ Uploading <b>{title}</b> ({file_size_mb:.1f} MB)...")

        caption = (
            f"🎧 <b><a href='{web_url}'>{title}</a></b>\n"
            f"👤 <b>Artist:</b> <code>{performer}</code> | ⏱ <b>Duration:</b> <code>{_format_duration(duration)}</code>"
        )

        target_chat = m.chat_id or getattr(m.chat, "id", None)
        await c.send_file(
            target_chat,
            audio_file,
            caption=caption,
            thumb=thumb_file if thumb_file and os.path.exists(thumb_file) else None,
            attributes=[],
            reply_to=m.id,
        )

        await msg.delete()

    except Exception as e:
        await msg.edit_msg(f"❌ Song error: <code>{e}</code>")
    finally:
        try:
            if 'vid_id' in locals():
                for fn in os.listdir(out_dir):
                    if fn.startswith(vid_id):
                        try:
                            os.remove(os.path.join(out_dir, fn))
                        except Exception:
                            pass
        except Exception:
            pass


@Altruix.register_on_cmd(
    ["ytsearch", "yts"],
    cmd_help={
        "help": "Search YouTube for videos with metadata, view count, duration, and download commands.",
        "example": "ytsearch lofi beats to study to\nyts interstellar soundtrack",
    },
    requires_input=True,
)
async def youtube_search_list(c: Client, m: Message):
    if not HAS_YTDL:
        return await m.handle_message("❌ <code>yt-dlp</code> is required.")

    query = m.user_input.strip()
    msg = await m.handle_message(f"🔍 Searching YouTube for <b>{query}</b>...")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
    }

    try:
        loop = asyncio.get_running_loop()

        def _search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(f"ytsearch5:{query}", download=False)

        res = await loop.run_in_executor(None, _search)
        entries = res.get("entries", []) if res else []

        if not entries:
            return await msg.edit_msg(f"🤷‍♂️ No YouTube results found for <code>{query}</code>.")

        cards = []
        for i, item in enumerate(entries[:5], 1):
            vid_id = item.get("id")
            title = item.get("title", "Untitled")
            duration = _format_duration(item.get("duration"))
            channel = item.get("uploader") or item.get("channel", "YouTube")
            views = _format_count(item.get("view_count"))
            url = f"https://youtu.be/{vid_id}"

            card = (
                f"<b>{i}. <a href='{url}'>{title}</a></b>\n"
                f"   ⏱ <code>{duration}</code> | 👁 <code>{views} views</code> | 👤 <code>{channel}</code>\n"
                f"   <i>Download:</i> <code>.ytdl {vid_id}</code> | <code>.ytmp3 {vid_id}</code>"
            )
            cards.append(card)

        report = (
            f"🎬 <b>YouTube Search Results for:</b> <code>{query}</code>\n\n"
            + "\n\n".join(cards)
            + "\n\n💡 <i>Tip: Copy any command above to download instantly!</i>"
        )

        await msg.edit_msg(report, disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_msg(f"❌ YouTube search error: <code>{e}</code>")


@Altruix.register_on_cmd(
    ["ytinfo"],
    cmd_help={
        "help": "Display technical video specifications, available formats, view counts, and channel metadata.",
        "example": "ytinfo https://youtu.be/...",
    },
    requires_input=True,
)
async def youtube_info_inspect(c: Client, m: Message):
    if not HAS_YTDL:
        return await m.handle_message("❌ <code>yt-dlp</code> is required.")

    query = m.user_input.strip()
    msg = await m.handle_message(f"🔍 Fetching technical metadata for <b>{query}</b>...")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    try:
        loop = asyncio.get_running_loop()

        def _get_info():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(query, download=False)

        info = await loop.run_in_executor(None, _get_info)

        title = info.get("title", "Untitled")
        vid_id = info.get("id")
        duration = _format_duration(info.get("duration"))
        views = _format_count(info.get("view_count"))
        likes = _format_count(info.get("like_count"))
        channel = info.get("uploader") or info.get("channel", "Unknown")
        upload_date = info.get("upload_date") or "Unknown"
        if len(upload_date) == 8:
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

        formats = info.get("formats", [])
        resolutions = sorted(list({f.get("height") for f in formats if f.get("height")}), reverse=True)
        res_str = ", ".join([f"{r}p" for r in resolutions[:6]]) if resolutions else "Standard"

        desc = (info.get("description") or "").strip()
        desc_snippet = f"<i>\"{desc[:200]}...\"</i>" if desc else "<i>No description</i>"

        report = (
            f"ℹ️ <b>YouTube Video Analysis:</b>\n\n"
            f"📌 <b>Title:</b> <code>{title}</code>\n"
            f"🆔 <b>Video ID:</b> <code>{vid_id}</code>\n"
            f"👤 <b>Channel:</b> <code>{channel}</code>\n"
            f"⏱ <b>Duration:</b> <code>{duration}</code>\n"
            f"👁 <b>Views:</b> <code>{views}</code> | 👍 <b>Likes:</b> <code>{likes}</code>\n"
            f"📅 <b>Uploaded:</b> <code>{upload_date}</code>\n"
            f"📺 <b>Resolutions:</b> <code>{res_str}</code>\n\n"
            f"<b>Description:</b>\n{desc_snippet}"
        )

        await msg.edit_msg(report, disable_web_page_preview=True)

    except Exception as e:
        await msg.edit_msg(f"❌ YouTube info error: <code>{e}</code>")
