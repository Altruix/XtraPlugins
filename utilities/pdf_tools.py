# Copyright (C) 2021-present by Altruix@Github, < https://github.com/Altruix >.
#
# This file is part of < https://github.com/Altruix/Altruix > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/Altriux/Altruix/blob/main/LICENSE >
#
# All rights reserved.

import os
import asyncio
from typing import Optional
from Main import Altruix
from Main.core.types.client import AltruixTelegramClient as Client
from Main.core.types.message import Message
from Main.utils.essentials import Essentials

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _check_pil():
    if not HAS_PIL:
        raise RuntimeError("Pillow is required for PDF tools.")


def _text_to_pdf(text: str, out_pdf_path: str) -> None:
    """Render multi-line text into a clean paginated PDF document."""
    # Standard A4 at 150 DPI: 1240 x 1754 px
    page_width, page_height = 1240, 1754
    margin = 80
    usable_width = page_width - (2 * margin)

    font = ImageFont.load_default()
    line_height = 28

    lines = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split()
        curr_line = ""
        for word in words:
            test_line = f"{curr_line} {word}".strip()
            # Rough character width estimate with default font
            if len(test_line) * 9 > usable_width:
                lines.append(curr_line)
                curr_line = word
            else:
                curr_line = test_line
        if curr_line:
            lines.append(curr_line)

    lines_per_page = (page_height - (2 * margin)) // line_height
    pages = []

    for i in range(0, max(1, len(lines)), lines_per_page):
        chunk = lines[i:i + lines_per_page]
        img = Image.new("RGB", (page_width, page_height), "white")
        draw = ImageDraw.Draw(img)

        # Header accent bar
        draw.rectangle([(margin, 50), (page_width - margin, 54)], fill=(41, 128, 185))

        y = margin
        for line in chunk:
            draw.text((margin, y), line, fill=(30, 30, 30), font=font)
            y += line_height

        pages.append(img)

    if pages:
        first_page = pages[0]
        other_pages = pages[1:] if len(pages) > 1 else []
        first_page.save(out_pdf_path, "PDF", resolution=150.0, save_all=True, append_images=other_pages)


@Altruix.register_on_cmd(
    ["topdf", "pdf"],
    cmd_help={
        "help": "Convert text or replied image/document to a formatted PDF file.",
        "example": "topdf My text here or topdf (replying to photo/text)",
    },
)
async def create_pdf(c: Client, m: Message):
    _check_pil()
    msg = await m.handle_message("📄 Generating PDF document...")
    os.makedirs("temp/xtra_pdf", exist_ok=True)
    out_pdf = f"temp/xtra_pdf/document_{m.id}.pdf"

    text_input = (m.user_input or "").strip()
    rm = m.reply_to_message or (await m.get_reply_message() if hasattr(m, "get_reply_message") else None)

    try:
        # Check if replying to an image
        if rm and (rm.photo or (rm.file and rm.file.mime_type and rm.file.mime_type.startswith("image/"))):
            await msg.edit_msg("🖼 Downloading replied image...")
            img_path = await rm.download_media("temp/xtra_pdf/")
            if img_path and os.path.exists(img_path):
                def _convert_img():
                    with Image.open(img_path) as im:
                        rgb_im = im.convert("RGB")
                        rgb_im.save(out_pdf, "PDF", resolution=100.0)

                await asyncio.get_running_loop().run_in_executor(None, _convert_img)
                if os.path.exists(img_path):
                    os.remove(img_path)
            else:
                return await msg.edit_msg("❌ Failed to download replied image.")

        else:
            # Text to PDF
            if not text_input and rm and (rm.text or rm.caption):
                text_input = rm.text or rm.caption

            if not text_input:
                return await msg.edit_msg("❌ Please provide text or reply to an image/text to convert to PDF.")

            await asyncio.get_running_loop().run_in_executor(None, lambda: _text_to_pdf(text_input, out_pdf))

        if not os.path.exists(out_pdf):
            return await msg.edit_msg("❌ PDF creation failed.")

        pdf_size = Essentials.humanbytes(os.path.getsize(out_pdf))
        target_chat = m.chat_id or getattr(m.chat, "id", None)
        await c.send_file(
            target_chat,
            out_pdf,
            caption=f"📄 <b>PDF Created Successfully</b>\n<b>Size:</b> <code>{pdf_size}</code>",
            reply_to=m.id,
        )
        try:

            await msg.delete()

        except Exception:

            pass
    except Exception as e:
        await msg.edit_msg(f"❌ Failed to create PDF: <code>{e}</code>")
    finally:
        if os.path.exists(out_pdf):
            try:
                os.remove(out_pdf)
            except Exception:
                pass


@Altruix.register_on_cmd(
    ["pdfinfo"],
    cmd_help={
        "help": "Inspect metadata and page count of a replied PDF file.",
        "example": "pdfinfo (replying to .pdf)",
    },
    requires_reply=True,
)
async def pdf_info(c: Client, m: Message):
    rm = m.reply_to_message or (await m.get_reply_message() if hasattr(m, "get_reply_message") else None)
    if not rm or not rm.file or not (rm.file.name and rm.file.name.lower().endswith(".pdf")):
        return await m.handle_message("❌ Please reply to a valid PDF file.")

    msg = await m.handle_message("🔍 Inspecting PDF metadata...")
    os.makedirs("temp/xtra_pdf", exist_ok=True)
    pdf_path = await rm.download_media("temp/xtra_pdf/")

    if not pdf_path or not os.path.exists(pdf_path):
        return await msg.edit_msg("❌ Failed to download PDF.")

    try:
        # Read PDF binary headers to count /Type /Page
        with open(pdf_path, "rb") as f:
            content = f.read()

        pages_count = content.count(b"/Type /Page") or content.count(b"/Type/Page") or "N/A"
        file_size = Essentials.humanbytes(len(content))
        filename = os.path.basename(pdf_path)

        report = (
            f"📄 <b>PDF Document Information:</b>\n\n"
            f"<b>• File:</b> <code>{filename}</code>\n"
            f"<b>• Size:</b> <code>{file_size}</code>\n"
            f"<b>• Estimated Pages:</b> <code>{pages_count}</code>\n"
            f"<b>• Encrypted:</b> <code>{'Yes' if b'/Encrypt' in content else 'No'}</code>"
        )
        await msg.edit_msg(report)
    except Exception as e:
        await msg.edit_msg(f"❌ Failed to inspect PDF: <code>{e}</code>")
    finally:
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass
