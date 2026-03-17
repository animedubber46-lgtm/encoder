import os
from dotenv import load_dotenv

load_dotenv()

# Bot Configuration
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", 0))

# MongoDB Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "video_compressor")

# FFmpeg Settings
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE_PATH = os.getenv("FFPROBE_PATH", "ffprobe")

# Encoding Presets
PRESETS = {
    "480p": {
        "resolution": "854x480",
        "video_bitrate": "1M",
        "audio_bitrate": "128k",
        "crf": 28,
        "preset": "medium",
        "fps": 30
    },
    "720p": {
        "resolution": "1280x720",
        "video_bitrate": "2.5M",
        "audio_bitrate": "192k",
        "crf": 23,
        "preset": "medium",
        "fps": 30
    },
    "1080p": {
        "resolution": "1920x1080",
        "video_bitrate": "5M",
        "audio_bitrate": "256k",
        "crf": 20,
        "preset": "medium",
        "fps": 30
    }
}

# File size limit (2GB for Telegram)
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024

# Supported video formats
SUPPORTED_FORMATS = [
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", 
    ".m4v", ".mpeg", ".mpg", ".3gp", ".ts", ".mts", ".m2ts"
]

# Supported subtitle formats
SUBTITLE_FORMATS = [".srt", ".ass", ".ssa", ".vtt", ".sub"]

# Supported audio formats
AUDIO_FORMATS = [".mp3", ".aac", ".wav", ".flac", ".m4a", ".ogg", ".opus"]

# Bot info
BOT_VERSION = "1.0.0"
BOT_NAME = "Video Compressor Bot"
DEVELOPER = "Shivam Bot Updates"