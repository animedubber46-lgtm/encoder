import os
import sys
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
)
from pyrogram.errors import (
    UserNotParticipant, MessageNotModified, 
    MessageDeleteForbidden, FloodWait
)

from config import (
    API_ID, API_HASH, BOT_TOKEN, OWNER_ID, LOG_CHANNEL,
    PRESETS, SUPPORTED_FORMATS, SUBTITLE_FORMATS, AUDIO_FORMATS,
    MAX_FILE_SIZE, BOT_VERSION, BOT_NAME, DEVELOPER
)
from database import db
from encoder import encoder
from utils import (
    task_queue, file_manager, SystemInfo, TaskStatus,
    generate_task_id, format_size, format_duration,
    is_valid_time_format, parse_time_to_seconds
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Create necessary directories
os.makedirs("logs", exist_ok=True)
os.makedirs("downloads", exist_ok=True)

# Initialize Pyrogram client
app = Client(
    "video_compressor_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=20
)

# Store user states for multi-step operations
user_states: Dict[int, Dict[str, Any]] = {}

# Store pending video tasks
pending_videos: Dict[int, Dict[str, Any]] = {}


def is_owner(user_id: int) -> bool:
    """Check if user is owner"""
    return user_id == OWNER_ID


async def is_authorized(chat_id: int) -> bool:
    """Check if chat is authorized"""
    return await db.is_chat_authorized(chat_id)


def get_quality_keyboard() -> InlineKeyboardMarkup:
    """Get quality selection keyboard"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 480p", callback_data="quality_480p"),
            InlineKeyboardButton("📱 720p", callback_data="quality_720p")
        ],
        [
            InlineKeyboardButton("📱 1080p", callback_data="quality_1080p"),
            InlineKeyboardButton("❌ Cancel", callback_data="quality_cancel")
        ]
    ])


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Get settings keyboard"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("480p Settings", callback_data="settings_480p"),
            InlineKeyboardButton("720p Settings", callback_data="settings_720p")
        ],
        [
            InlineKeyboardButton("1080p Settings", callback_data="settings_1080p"),
            InlineKeyboardButton("🔙 Back", callback_data="settings_back")
        ]
    ])


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Get main menu keyboard"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("🎬 Compress Video"), KeyboardButton("⚙️ Settings")],
        [KeyboardButton("📊 Status"), KeyboardButton("ℹ️ Help")]
    ], resize_keyboard=True)


async def progress_callback(task_id: str, message: Message, progress: int):
    """Update progress message"""
    try:
        task = await task_queue.get_task(task_id)
        if task:
            text = f"""
🎬 **Processing Video**

📁 **File:** `{task.file_name}`
📱 **Quality:** {task.quality}
📊 **Progress:** {progress}%

{'▓' * (progress // 10)}{'░' * (10 - progress // 10)} {progress}%

⏳ Please wait...
"""
            try:
                await message.edit_text(text)
            except MessageNotModified:
                pass
    except Exception as e:
        logger.error(f"Error updating progress: {e}")


async def send_to_log_channel(text: str, file_path: str = None):
    """Send message to log channel"""
    try:
        if file_path and os.path.exists(file_path):
            await app.send_document(LOG_CHANNEL, file_path, caption=text)
        else:
            await app.send_message(LOG_CHANNEL, text)
    except Exception as e:
        logger.error(f"Error sending to log channel: {e}")


async def process_video_task(task_id: str, progress_msg: Message):
    """Process a video compression task"""
    task = await task_queue.get_task(task_id)
    if not task:
        return
    
    try:
        # Update status
        await db.update_task_status(task_id, "processing", 0)
        
        # Get file paths
        input_path = task.file_path
        base_name = os.path.splitext(task.file_name)[0]
        output_path = file_manager.get_output_path(f"{base_name}_{task.quality}.mp4")
        
        # Progress callback
        async def update_progress(progress: int):
            await progress_callback(task_id, progress_msg, progress)
            await db.update_task_status(task_id, "processing", progress)
        
        # Compress video
        success, message = await encoder.compress_video(
            input_path, output_path, task.quality, task_id, update_progress
        )
        
        if success and os.path.exists(output_path):
            # Send to user in PM
            try:
                await app.send_document(
                    task.user_id,
                    output_path,
                    caption=f"""
✅ **Video Compressed Successfully**

📁 **Original:** `{task.file_name}`
📱 **Quality:** {task.quality}
📦 **Size:** {format_size(os.path.getsize(output_path))}

🤖 **Bot by:** {DEVELOPER}
""",
                    progress_args=(
                        "📤 Uploading...",
                        progress_msg,
                        5
                    )
                )
                
                # Log completion
                await send_to_log_channel(
                    f"✅ Task Completed\n\n"
                    f"**Task ID:** `{task_id}`\n"
                    f"**User ID:** `{task.user_id}`\n"
                    f"**File:** `{task.file_name}`\n"
                    f"**Quality:** {task.quality}"
                )
                
            except Exception as e:
                logger.error(f"Error sending compressed video: {e}")
                await app.send_message(
                    task.user_id,
                    f"❌ Failed to send compressed video. Error: {str(e)}"
                )
            
            # Cleanup
            file_manager.cleanup_file(input_path)
            file_manager.cleanup_file(output_path)
            
            await db.update_task_status(task_id, "completed", 100)
            await task_queue.complete_task(task_id, True)
            
        else:
            # Task failed or cancelled
            await db.update_task_status(task_id, "failed", 0)
            await task_queue.complete_task(task_id, False, message)
            
            await app.send_message(
                task.user_id,
                f"❌ **Compression Failed**\n\n**Error:** {message}"
            )
            
            # Cleanup
            file_manager.cleanup_file(input_path)
            if os.path.exists(output_path):
                file_manager.cleanup_file(output_path)
        
        # Delete progress message
        try:
            await progress_msg.delete()
        except Exception:
            pass
            
    except Exception as e:
        logger.error(f"Error processing task {task_id}: {e}")
        await task_queue.complete_task(task_id, False, str(e))
        await db.update_task_status(task_id, "failed", 0)


# ==================== COMMAND HANDLERS ====================

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    user = message.from_user
    await db.add_user(user.id, user.username or "", user.first_name)
    
    text = f"""
👋 **Hello {user.first_name}!**

Welcome to **{BOT_NAME}**! 🎬

I can compress your videos in different qualities:
• 480p - Smaller size, lower quality
• 720p - Balanced size and quality
• 1080p - Best quality, larger size

**Features:**
• Video compression (480p, 720p, 1080p)
• Extract audio from videos
• Add/remove audio
• Add soft/hard subtitles
• Trim videos
• And more!

Use /help to see all commands.

🤖 **Version:** {BOT_VERSION}
👨‍💻 **Developer:** {DEVELOPER}
"""
    await message.reply(text, reply_markup=get_main_keyboard())


@app.on_message(filters.command("start") & filters.group)
async def start_group_command(client: Client, message: Message):
    """Handle /start in groups"""
    if not await is_authorized(message.chat.id):
        await message.reply("❌ This group is not authorized to use this bot.")
        return
    
    text = f"""
👋 **Hello!**

I'm **{BOT_NAME}**! 🎬

Send me a video to compress it in your preferred quality.

Use /help to see all commands.
"""
    await message.reply(text)


@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    """Handle /help command"""
    text = """
🤖 **Available Commands**

**Encoding:**
• /compress - Compress video (Interactive)
• /settings - 480p settings
• /settings1 - 720p settings
• /settings2 - 1080p settings
• /all - Encode 480p, 720p, & 1080p

**Media Tools:**
• /extract_audio - Extract audio (MP3/AAC/etc)
• /addaudio - Add audio to video (Reply to audio)
• /remaudio - Remove audio from video
• /sub - Add soft subtitles (Reply to sub)
• /hsub - Add hard subtitles (Reply to sub)
• /rsub - Remove all subtitles
• /trim - Trim video (Start - End)
• /mediainfo - Get detailed media info

**Utility:**
• /list - Show active queue
• /cancel - Cancel task (Use /cancel ID)
• /sysinfo - System info
• /speedtest - Network speed test
• /ping - Check latency
• /start - Check status
• /restart - Restart bot (Admin)
• /update - Update bot (Admin)
• /log - Get logs (Admin)

**Maintained By:** Shivam Bot Updates
"""
    await message.reply(text)


@app.on_message(filters.command("compress"))
async def compress_command(client: Client, message: Message):
    """Handle /compress command"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎬 **Send me a video to compress**\n\n"
        "Supported formats: MP4, MKV, AVI, MOV, WEBM, etc.\n"
        "Max size: 2GB",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_video"}


@app.on_message(filters.command("settings"))
async def settings_command(client: Client, message: Message):
    """Handle /settings command - Show 480p settings"""
    preset = PRESETS.get("480p", {})
    text = f"""
📱 **480p Encoding Settings**

• **Resolution:** {preset.get('resolution', 'N/A')}
• **Video Bitrate:** {preset.get('video_bitrate', 'N/A')}
• **Audio Bitrate:** {preset.get('audio_bitrate', 'N/A')}
• **CRF:** {preset.get('crf', 'N/A')}
• **Preset:** {preset.get('preset', 'N/A')}
• **FPS:** {preset.get('fps', 'N/A')}

Best for: Mobile devices, slow internet
"""
    await message.reply(text)


@app.on_message(filters.command("settings1"))
async def settings1_command(client: Client, message: Message):
    """Handle /settings1 command - Show 720p settings"""
    preset = PRESETS.get("720p", {})
    text = f"""
📱 **720p Encoding Settings**

• **Resolution:** {preset.get('resolution', 'N/A')}
• **Video Bitrate:** {preset.get('video_bitrate', 'N/A')}
• **Audio Bitrate:** {preset.get('audio_bitrate', 'N/A')}
• **CRF:** {preset.get('crf', 'N/A')}
• **Preset:** {preset.get('preset', 'N/A')}
• **FPS:** {preset.get('fps', 'N/A')}

Best for: HD quality, balanced size
"""
    await message.reply(text)


@app.on_message(filters.command("settings2"))
async def settings2_command(client: Client, message: Message):
    """Handle /settings2 command - Show 1080p settings"""
    preset = PRESETS.get("1080p", {})
    text = f"""
📱 **1080p Encoding Settings**

• **Resolution:** {preset.get('resolution', 'N/A')}
• **Video Bitrate:** {preset.get('video_bitrate', 'N/A')}
• **Audio Bitrate:** {preset.get('audio_bitrate', 'N/A')}
• **CRF:** {preset.get('crf', 'N/A')}
• **Preset:** {preset.get('preset', 'N/A')}
• **FPS:** {preset.get('fps', 'N/A')}

Best for: Full HD quality, large screens
"""
    await message.reply(text)


@app.on_message(filters.command("all"))
async def all_qualities_command(client: Client, message: Message):
    """Handle /all command - Encode in all qualities"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎬 **Send me a video to compress in all qualities**\n\n"
        "I will encode it in 480p, 720p, and 1080p.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_video_all"}


@app.on_message(filters.command("extract_audio"))
async def extract_audio_command(client: Client, message: Message):
    """Handle /extract_audio command"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎵 **Send me a video to extract audio**\n\n"
        "Audio will be extracted in MP3 format.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_extract_audio"}


@app.on_message(filters.command("addaudio"))
async def add_audio_command(client: Client, message: Message):
    """Handle /addaudio command"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎬 **Send me a video to add audio**\n\n"
        "Then reply to an audio file with the video.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_video_addaudio"}


@app.on_message(filters.command("remaudio"))
async def remove_audio_command(client: Client, message: Message):
    """Handle /remaudio command"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎬 **Send me a video to remove audio**\n\n"
        "Audio track will be removed from the video.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_remove_audio"}


@app.on_message(filters.command("sub"))
async def add_soft_sub_command(client: Client, message: Message):
    """Handle /sub command - Add soft subtitle"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎬 **Send me a video to add soft subtitle**\n\n"
        "Then send the subtitle file (SRT, ASS, VTT).",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_video_sub"}


@app.on_message(filters.command("hsub"))
async def add_hard_sub_command(client: Client, message: Message):
    """Handle /hsub command - Add hard subtitle"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎬 **Send me a video to add hard subtitle**\n\n"
        "Subtitle will be burned into the video.\n"
        "Then send the subtitle file (SRT, ASS, VTT).",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_video_hsub"}


@app.on_message(filters.command("rsub"))
async def remove_sub_command(client: Client, message: Message):
    """Handle /rsub command - Remove subtitles"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎬 **Send me a video to remove subtitles**\n\n"
        "All subtitle tracks will be removed.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_remove_sub"}


@app.on_message(filters.command("trim"))
async def trim_command(client: Client, message: Message):
    """Handle /trim command"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎬 **Send me a video to trim**\n\n"
        "After sending the video, provide start and end time.\n"
        "Format: `HH:MM:SS` or `MM:SS` or `SS`",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_trim_video"}


@app.on_message(filters.command("mediainfo"))
async def mediainfo_command(client: Client, message: Message):
    """Handle /mediainfo command"""
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            await message.reply("❌ This group is not authorized.")
            return
    
    await message.reply(
        "🎬 **Send me a video to get media info**\n\n"
        "I'll show detailed information about the video.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="compress_cancel")]
        ])
    )
    
    user_states[message.from_user.id] = {"state": "waiting_mediainfo"}


@app.on_message(filters.command("list"))
async def list_command(client: Client, message: Message):
    """Handle /list command - Show active queue"""
    active_tasks = await task_queue.get_active_tasks()
    
    if not active_tasks:
        await message.reply("📋 **No active tasks in queue**")
        return
    
    text = "📋 **Active Tasks**\n\n"
    for i, task in enumerate(active_tasks, 1):
        status_emoji = "⏳" if task.status == TaskStatus.PENDING else "🔄"
        text += f"{i}. {status_emoji} `{task.task_id}`\n"
        text += f"   📁 {task.file_name}\n"
        text += f"   📱 {task.quality} | {task.progress}%\n\n"
    
    await message.reply(text)


@app.on_message(filters.command("cancel"))
async def cancel_command(client: Client, message: Message):
    """Handle /cancel command"""
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        # Show user's tasks
        user_tasks = await task_queue.get_user_tasks(message.from_user.id)
        active_tasks = [t for t in user_tasks if t.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]]
        
        if not active_tasks:
            await message.reply("❌ You have no active tasks to cancel.")
            return
        
        text = "📋 **Your Active Tasks**\n\n"
        text += "Use `/cancel TASK_ID` to cancel a task.\n\n"
        for task in active_tasks:
            text += f"• `{task.task_id}` - {task.file_name}\n"
        
        await message.reply(text)
        return
    
    task_id = args[1].strip().upper()
    task = await task_queue.get_task(task_id)
    
    if not task:
        await message.reply(f"❌ Task `{task_id}` not found.")
        return
    
    if task.user_id != message.from_user.id and not is_owner(message.from_user.id):
        await message.reply("❌ You can only cancel your own tasks.")
        return
    
    if task.status not in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
        await message.reply(f"❌ Task `{task_id}` is already completed/cancelled.")
        return
    
    # Cancel the task
    encoder.cancel_task(task_id)
    await task_queue.cancel_task(task_id)
    await db.update_task_status(task_id, "cancelled", 0)
    
    await message.reply(f"✅ Task `{task_id}` has been cancelled.")


@app.on_message(filters.command("sysinfo"))
async def sysinfo_command(client: Client, message: Message):
    """Handle /sysinfo command"""
    info = SystemInfo.get_system_info()
    await message.reply(info)


@app.on_message(filters.command("speedtest"))
async def speedtest_command(client: Client, message: Message):
    """Handle /speedtest command"""
    msg = await message.reply("🔄 Running speed test...")
    result = await SystemInfo.speedtest()
    await msg.edit(result)


@app.on_message(filters.command("ping"))
async def ping_command(client: Client, message: Message):
    """Handle /ping command"""
    start = datetime.now()
    msg = await message.reply("🏓 Pong!")
    end = datetime.now()
    latency = (end - start).total_seconds() * 1000
    await msg.edit(f"🏓 Pong! `{latency:.2f}ms`")


# ==================== ADMIN COMMANDS ====================

@app.on_message(filters.command("auth") & filters.group)
async def auth_command(client: Client, message: Message):
    """Handle /auth command - Authorize a group"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Only the owner can authorize groups.")
        return
    
    chat = message.chat
    success = await db.authorize_chat(chat.id, chat.title, message.from_user.id)
    
    if success:
        await message.reply(f"✅ **{chat.title}** has been authorized!")
        await send_to_log_channel(f"✅ Group Authorized: **{chat.title}** (`{chat.id}`)")
    else:
        await message.reply("❌ Failed to authorize group. It may already be authorized.")


@app.on_message(filters.command("deauth") & filters.group)
async def deauth_command(client: Client, message: Message):
    """Handle /deauth command - Deauthorize a group"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Only the owner can deauthorize groups.")
        return
    
    chat = message.chat
    success = await db.deauthorize_chat(chat.id)
    
    if success:
        await message.reply(f"✅ **{chat.title}** has been deauthorized!")
        await send_to_log_channel(f"❌ Group Deauthorized: **{chat.title}** (`{chat.id}`)")
    else:
        await message.reply("❌ Failed to deauthorize group.")


@app.on_message(filters.command("restart"))
async def restart_command(client: Client, message: Message):
    """Handle /restart command"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Only the owner can restart the bot.")
        return
    
    await message.reply("🔄 Restarting bot...")
    await send_to_log_channel("🔄 Bot restarted by owner.")
    
    # Graceful restart
    os.execv(sys.executable, [sys.executable] + sys.argv)


@app.on_message(filters.command("update"))
async def update_command(client: Client, message: Message):
    """Handle /update command"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Only the owner can update the bot.")
        return
    
    await message.reply("🔄 Updating bot...")
    
    # Git pull
    import subprocess
    result = subprocess.run(["git", "pull"], capture_output=True, text=True)
    
    if result.returncode == 0:
        await message.reply(f"✅ Updated!\n\n```\n{result.stdout}\n```")
        await send_to_log_channel("🔄 Bot updated by owner.")
    else:
        await message.reply(f"❌ Update failed!\n\n```\n{result.stderr}\n```")


@app.on_message(filters.command("log"))
async def log_command(client: Client, message: Message):
    """Handle /log command"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Only the owner can view logs.")
        return
    
    log_file = "logs/bot.log"
    if os.path.exists(log_file):
        await message.reply_document(log_file, caption="📋 **Bot Logs**")
    else:
        await message.reply("❌ No log file found.")


@app.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    """Handle /stats command - Show bot statistics"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Only the owner can view stats.")
        return
    
    users_count = await db.get_users_count()
    active_tasks = await task_queue.get_active_tasks()
    authorized_chats = await db.get_authorized_chats()
    
    text = f"""
📊 **Bot Statistics**

👥 **Total Users:** {users_count}
🔄 **Active Tasks:** {len(active_tasks)}
✅ **Authorized Chats:** {len(authorized_chats)}
"""
    await message.reply(text)


@app.on_message(filters.command("broadcast"))
async def broadcast_command(client: Client, message: Message):
    """Handle /broadcast command"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Only the owner can broadcast.")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Usage: `/broadcast <message>`")
        return
    
    broadcast_msg = args[1]
    users = await db.get_all_users()
    
    success = 0
    failed = 0
    
    status_msg = await message.reply(f"📢 Broadcasting to {len(users)} users...")
    
    for user in users:
        try:
            await app.send_message(user["user_id"], broadcast_msg)
            success += 1
            await asyncio.sleep(0.1)  # Avoid flood
        except Exception:
            failed += 1
    
    await status_msg.edit(
        f"📢 **Broadcast Complete**\n\n"
        f"✅ Success: {success}\n"
        f"❌ Failed: {failed}"
    )


# ==================== VIDEO HANDLER ====================

@app.on_message(filters.video | filters.document)
async def handle_video(client: Client, message: Message):
    """Handle incoming video/document"""
    user_id = message.from_user.id
    
    # Check authorization for groups
    if message.chat.type != enums.ChatType.PRIVATE:
        if not await is_authorized(message.chat.id):
            return
    
    # Get the video/document
    if message.video:
        media = message.video
    elif message.document and any(
        message.document.file_name.lower().endswith(ext) 
        for ext in SUPPORTED_FORMATS
    ):
        media = message.document
    else:
        # Check if user is in a state that expects a file
        state = user_states.get(user_id, {}).get("state")
        if state and state.startswith("waiting"):
            await message.reply("❌ Please send a valid video file.")
        return
    
    # Check file size
    if media.file_size > MAX_FILE_SIZE:
        await message.reply("❌ File too large! Maximum size is 2GB.")
        return
    
    # Get user state
    state = user_states.get(user_id, {}).get("state", "")
    
    # Handle based on state
    if state == "waiting_mediainfo":
        await handle_mediainfo(message, media)
        return
    
    if state == "waiting_extract_audio":
        await handle_extract_audio(message, media)
        return
    
    if state == "waiting_remove_audio":
        await handle_remove_audio(message, media)
        return
    
    if state == "waiting_remove_sub":
        await handle_remove_sub(message, media)
        return
    
    if state == "waiting_trim_video":
        await handle_trim_video(message, media)
        return
    
    # For compression, show quality selection
    file_name = media.file_name or f"video_{media.file_unique_id}.mp4"
    
    # Store pending video info
    pending_videos[user_id] = {
        "message": message,
        "media": media,
        "file_name": file_name,
        "chat_id": message.chat.id,
        "message_id": message.id,
        "is_all": state == "waiting_video_all"
    }
    
    # Ask for quality
    ask_msg = await message.reply(
        f"🎬 **Video Received**\n\n"
        f"📁 **File:** `{file_name}`\n"
        f"📦 **Size:** {format_size(media.file_size)}\n\n"
        f"**Select quality to compress:**",
        reply_markup=get_quality_keyboard()
    )
    
    pending_videos[user_id]["ask_msg"] = ask_msg
    
    # Clear state
    user_states.pop(user_id, None)


async def handle_mediainfo(message: Message, media):
    """Handle mediainfo request"""
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    
    status_msg = await message.reply("📥 Downloading video...")
    
    try:
        file_path = file_manager.get_temp_path(media.file_name or "video.mp4")
        await app.download_media(media, file_name=file_path, progress=status_msg.edit)
        
        await status_msg.edit("🔍 Getting media info...")
        info = await encoder.get_media_info(file_path)
        
        await message.reply(info)
        file_manager.cleanup_file(file_path)
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)}")


async def handle_extract_audio(message: Message, media):
    """Handle audio extraction"""
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    
    status_msg = await message.reply("📥 Downloading video...")
    
    try:
        file_path = file_manager.get_temp_path(media.file_name or "video.mp4")
        await app.download_media(media, file_name=file_path, progress=status_msg.edit)
        
        base_name = os.path.splitext(media.file_name or "video")[0]
        output_path = file_manager.get_output_path(f"{base_name}.mp3")
        
        await status_msg.edit("🎵 Extracting audio...")
        
        success, msg = await encoder.extract_audio(file_path, output_path)
        
        if success:
            await app.send_document(
                user_id,
                output_path,
                caption=f"✅ **Audio Extracted**\n\n📁 `{base_name}.mp3`"
            )
            file_manager.cleanup_file(output_path)
        else:
            await message.reply(f"❌ {msg}")
        
        file_manager.cleanup_file(file_path)
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)}")


async def handle_remove_audio(message: Message, media):
    """Handle audio removal"""
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    
    status_msg = await message.reply("📥 Downloading video...")
    
    try:
        file_path = file_manager.get_temp_path(media.file_name or "video.mp4")
        await app.download_media(media, file_name=file_path, progress=status_msg.edit)
        
        base_name = os.path.splitext(media.file_name or "video")[0]
        output_path = file_manager.get_output_path(f"{base_name}_no_audio.mp4")
        
        await status_msg.edit("🔇 Removing audio...")
        
        success, msg = await encoder.remove_audio(file_path, output_path)
        
        if success:
            await app.send_document(
                user_id,
                output_path,
                caption=f"✅ **Audio Removed**\n\n📁 `{base_name}_no_audio.mp4`"
            )
            file_manager.cleanup_file(output_path)
        else:
            await message.reply(f"❌ {msg}")
        
        file_manager.cleanup_file(file_path)
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)}")


async def handle_remove_sub(message: Message, media):
    """Handle subtitle removal"""
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    
    status_msg = await message.reply("📥 Downloading video...")
    
    try:
        file_path = file_manager.get_temp_path(media.file_name or "video.mp4")
        await app.download_media(media, file_name=file_path, progress=status_msg.edit)
        
        base_name = os.path.splitext(media.file_name or "video")[0]
        output_path = file_manager.get_output_path(f"{base_name}_no_sub.mp4")
        
        await status_msg.edit("📝 Removing subtitles...")
        
        success, msg = await encoder.remove_subtitles(file_path, output_path)
        
        if success:
            await app.send_document(
                user_id,
                output_path,
                caption=f"✅ **Subtitles Removed**\n\n📁 `{base_name}_no_sub.mp4`"
            )
            file_manager.cleanup_file(output_path)
        else:
            await message.reply(f"❌ {msg}")
        
        file_manager.cleanup_file(file_path)
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)}")


async def handle_trim_video(message: Message, media):
    """Handle video trimming - step 1: download"""
    user_id = message.from_user.id
    
    status_msg = await message.reply("📥 Downloading video...")
    
    try:
        file_path = file_manager.get_temp_path(media.file_name or "video.mp4")
        await app.download_media(media, file_name=file_path, progress=status_msg.edit)
        
        # Store for next step
        user_states[user_id] = {
            "state": "waiting_trim_time",
            "file_path": file_path,
            "file_name": media.file_name or "video.mp4"
        }
        
        await status_msg.edit(
            "✂️ **Video downloaded!**\n\n"
            "Now send the trim times in format:\n"
            "`START_TIME END_TIME`\n\n"
            "Example: `00:01:30 00:05:00`\n"
            "Or: `90 300` (in seconds)"
        )
        
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)}")


@app.on_message(filters.text & filters.private)
async def handle_text(client: Client, message: Message):
    """Handle text messages for multi-step operations"""
    user_id = message.from_user.id
    state_data = user_states.get(user_id, {})
    state = state_data.get("state", "")
    
    if state == "waiting_trim_time":
        await process_trim_time(message, state_data)
        return
    
    # Handle menu buttons
    if message.text == "🎬 Compress Video":
        await compress_command(client, message)
    elif message.text == "⚙️ Settings":
        await message.reply("Select settings to view:", reply_markup=get_settings_keyboard())
    elif message.text == "📊 Status":
        await list_command(client, message)
    elif message.text == "ℹ️ Help":
        await help_command(client, message)


async def process_trim_time(message: Message, state_data: dict):
    """Process trim time input"""
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    
    try:
        # Parse time input
        parts = message.text.strip().split()
        if len(parts) != 2:
            await message.reply("❌ Invalid format. Use: `START_TIME END_TIME`")
            return
        
        start_time = parts[0]
        end_time = parts[1]
        
        # Convert to seconds if needed
        if ":" in start_time:
            start_seconds = parse_time_to_seconds(start_time)
        else:
            start_seconds = int(start_time)
        
        if ":" in end_time:
            end_seconds = parse_time_to_seconds(end_time)
        else:
            end_seconds = int(end_time)
        
        if start_seconds >= end_seconds:
            await message.reply("❌ Start time must be before end time.")
            return
        
        file_path = state_data["file_path"]
        file_name = state_data["file_name"]
        base_name = os.path.splitext(file_name)[0]
        output_path = file_manager.get_output_path(f"{base_name}_trimmed.mp4")
        
        status_msg = await message.reply("✂️ Trimming video...")
        
        success, msg = await encoder.trim_video(
            file_path, output_path,
            str(start_seconds), str(end_seconds)
        )
        
        if success:
            await app.send_document(
                user_id,
                output_path,
                caption=f"✅ **Video Trimmed**\n\n"
                        f"📁 `{base_name}_trimmed.mp4`\n"
                        f"⏱ From {start_time} to {end_time}"
            )
            file_manager.cleanup_file(output_path)
        else:
            await message.reply(f"❌ {msg}")
        
        file_manager.cleanup_file(file_path)
        await status_msg.delete()
        
    except ValueError:
        await message.reply("❌ Invalid time format. Use HH:MM:SS or seconds.")
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")


# ==================== CALLBACK HANDLERS ====================

@app.on_callback_query()
async def handle_callback(client: Client, callback: CallbackQuery):
    """Handle callback queries"""
    user_id = callback.from_user.id
    data = callback.data
    
    if data == "compress_cancel":
        user_states.pop(user_id, None)
        pending_videos.pop(user_id, None)
        await callback.message.edit_text("❌ Cancelled.")
        return
    
    if data == "settings_back":
        await callback.message.delete()
        return
    
    if data.startswith("settings_"):
        quality = data.replace("settings_", "")
        preset = PRESETS.get(quality, {})
        text = f"""
📱 **{quality} Encoding Settings**

• **Resolution:** {preset.get('resolution', 'N/A')}
• **Video Bitrate:** {preset.get('video_bitrate', 'N/A')}
• **Audio Bitrate:** {preset.get('audio_bitrate', 'N/A')}
• **CRF:** {preset.get('crf', 'N/A')}
• **Preset:** {preset.get('preset', 'N/A')}
• **FPS:** {preset.get('fps', 'N/A')}
"""
        await callback.message.edit_text(text)
        return
    
    if data.startswith("quality_"):
        quality = data.replace("quality_", "")
        
        if quality == "cancel":
            user_states.pop(user_id, None)
            pending_videos.pop(user_id, None)
            await callback.message.edit_text("❌ Cancelled.")
            return
        
        # Get pending video
        pending = pending_videos.get(user_id)
        if not pending:
            await callback.answer("❌ No pending video. Please send a video first.")
            return
        
        # Delete original message for security
        try:
            await pending["message"].delete()
        except MessageDeleteForbidden:
            pass
        
        # Delete the quality selection message
        try:
            await callback.message.delete()
        except Exception:
            pass
        
        # Start processing
        await start_compression(user_id, pending, quality, callback)


async def start_compression(user_id: int, pending: dict, quality: str, callback: CallbackQuery):
    """Start video compression"""
    media = pending["media"]
    file_name = pending["file_name"]
    chat_id = pending["chat_id"]
    message_id = pending["message_id"]
    is_all = pending.get("is_all", False)
    
    # Generate task ID
    task_id = generate_task_id()
    
    # Send status message
    status_msg = await callback.message.reply(
        f"📥 **Downloading Video**\n\n"
        f"📁 `{file_name}`\n"
        f"📱 Quality: {quality}"
    )
    
    try:
        # Download video
        file_path = file_manager.get_video_path(f"{task_id}_{file_name}")
        await app.download_media(media, file_name=file_path, progress=status_msg.edit)
        
        # Create task
        from utils import Task
        task = Task(
            task_id=task_id,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            file_name=file_name,
            quality=quality,
            file_path=file_path
        )
        
        await task_queue.add_task(task)
        await db.add_task(task_id, user_id, chat_id, message_id, file_name, quality)
        
        # Update status
        await status_msg.edit(
            f"⏳ **Task Added to Queue**\n\n"
            f"**Task ID:** `{task_id}`\n"
            f"📁 `{file_name}`\n"
            f"📱 Quality: {quality}\n\n"
            f"Processing will start shortly..."
        )
        
        # Clear pending
        pending_videos.pop(user_id, None)
        
        # Start processing
        progress_msg = await callback.message.reply(
            f"🎬 **Processing Video**\n\n"
            f"📁 `{file_name}`\n"
            f"📱 Quality: {quality}\n"
            f"📊 Progress: 0%"
        )
        
        await process_video_task(task_id, progress_msg)
        
    except Exception as e:
        logger.error(f"Error starting compression: {e}")
        await status_msg.edit(f"❌ Error: {str(e)}")
        pending_videos.pop(user_id, None)


# ==================== SUBTITLE HANDLER ====================

@app.on_message(filters.document)
async def handle_subtitle(client: Client, message: Message):
    """Handle subtitle files"""
    user_id = message.from_user.id
    state_data = user_states.get(user_id, {})
    state = state_data.get("state", "")
    
    if state not in ["waiting_video_sub", "waiting_video_hsub"]:
        return
    
    # Check if it's a subtitle file
    if not message.document.file_name:
        return
    
    file_ext = os.path.splitext(message.document.file_name)[1].lower()
    if file_ext not in SUBTITLE_FORMATS:
        await message.reply("❌ Please send a valid subtitle file (SRT, ASS, VTT).")
        return
    
    # Check if we have the video
    video_path = state_data.get("video_path")
    video_name = state_data.get("video_name")
    
    if not video_path:
        # Store subtitle and ask for video
        sub_path = file_manager.get_subtitle_path(message.document.file_name)
        await app.download_media(message.document, file_name=sub_path)
        
        user_states[user_id] = {
            "state": "waiting_sub_video",
            "sub_path": sub_path,
            "sub_name": message.document.file_name,
            "is_hard": state == "waiting_video_hsub"
        }
        
        await message.reply("✅ Subtitle received. Now send the video.")
        return


# ==================== AUDIO HANDLER ====================

@app.on_message(filters.audio | (filters.document & filters.regex(r"\.(mp3|aac|wav|flac|m4a|ogg|opus)$")))
async def handle_audio_file(client: Client, message: Message):
    """Handle audio files for adding to video"""
    user_id = message.from_user.id
    state_data = user_states.get(user_id, {})
    state = state_data.get("state", "")
    
    if state != "waiting_audio_file":
        return
    
    # Get audio
    if message.audio:
        audio = message.audio
    elif message.document:
        audio = message.document
    else:
        return
    
    video_path = state_data.get("video_path")
    video_name = state_data.get("video_name")
    
    if not video_path:
        await message.reply("❌ No video found. Please start over with /addaudio")
        user_states.pop(user_id, None)
        return
    
    status_msg = await message.reply("📥 Downloading audio...")
    
    try:
        audio_path = file_manager.get_audio_path(audio.file_name or "audio.mp3")
        await app.download_media(audio, file_name=audio_path, progress=status_msg.edit)
        
        base_name = os.path.splitext(video_name)[0]
        output_path = file_manager.get_output_path(f"{base_name}_with_audio.mp4")
        
        await status_msg.edit("🎵 Adding audio to video...")
        
        success, msg = await encoder.add_audio(video_path, audio_path, output_path)
        
        if success:
            await app.send_document(
                user_id,
                output_path,
                caption=f"✅ **Audio Added**\n\n📁 `{base_name}_with_audio.mp4`"
            )
            file_manager.cleanup_file(output_path)
        else:
            await message.reply(f"❌ {msg}")
        
        file_manager.cleanup_file(video_path)
        file_manager.cleanup_file(audio_path)
        await status_msg.delete()
        user_states.pop(user_id, None)
        
    except Exception as e:
        await status_msg.edit(f"❌ Error: {str(e)}")


# ==================== MAIN ====================

async def main():
    """Main function"""
    logger.info("Starting bot...")
    
    # Connect to database
    await db.connect()
    logger.info("Connected to database")
    
    # Start bot
    await app.start()
    logger.info("Bot started!")
    
    # Send startup message to log channel
    await send_to_log_channel(
        f"🚀 **{BOT_NAME} Started**\n\n"
        f"**Version:** {BOT_VERSION}\n"
        f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    # Keep running
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        asyncio.run(db.disconnect())