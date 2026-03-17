# Video Compressor Bot

A powerful Telegram video compressor bot with multiple features including video compression, audio extraction, subtitle handling, and more.

## Features

### Encoding
- **Video Compression** - Compress videos in 480p, 720p, or 1080p quality
- **Batch Encoding** - Encode in all qualities at once (480p, 720p, 1080p)
- **Custom Settings** - View encoding settings for each quality

### Media Tools
- **Extract Audio** - Extract audio from videos (MP3/AAC/etc)
- **Add Audio** - Add audio track to video
- **Remove Audio** - Remove audio from video
- **Soft Subtitles** - Add soft subtitles (SRT, ASS, VTT)
- **Hard Subtitles** - Burn subtitles into video
- **Remove Subtitles** - Remove all subtitle tracks
- **Trim Video** - Trim video with custom start/end times
- **Media Info** - Get detailed video information

### Utility
- **Task Queue** - View active tasks
- **Cancel Tasks** - Cancel running tasks
- **System Info** - View system statistics
- **Speed Test** - Test network speed
- **Ping** - Check bot latency

## Requirements

- Python 3.8 or higher
- FFmpeg installed on system
- MongoDB database
- Telegram Bot Token (from @BotFather)
- Telegram API ID and Hash (from my.telegram.org)

## Installation

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/video-compressor-bot.git
cd video-compressor-bot
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Install FFmpeg

**Windows:**
```bash
# Using Chocolatey
choco install ffmpeg

# Or download from https://ffmpeg.org/download.html
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

### 4. Configure the bot

Copy the example environment file:
```bash
cp .env.example .env
```

Edit `.env` with your configuration:
```env
# Bot Configuration
API_ID=your_api_id_here
API_HASH=your_api_hash_here
BOT_TOKEN=your_bot_token_here
OWNER_ID=your_telegram_user_id
LOG_CHANNEL=-100xxxxxxxxxx

# MongoDB Configuration
MONGODB_URI=mongodb://localhost:27017
DATABASE_NAME=video_compressor
```

### 5. Get Telegram credentials

1. Go to [my.telegram.org](https://my.telegram.org)
2. Log in with your phone number
3. Go to "API development tools"
4. Create a new application
5. Copy the `api_id` and `api_hash`

6. Go to [@BotFather](https://t.me/BotFather) on Telegram
7. Send `/newbot` and follow the instructions
8. Copy the bot token

9. Create a channel for logs
10. Add your bot as admin to the channel
11. Get the channel ID (forward a message from channel to @userinfobot)

### 6. Set up MongoDB

**Using local MongoDB:**
```bash
# Install MongoDB
sudo apt install mongodb

# Start MongoDB
sudo systemctl start mongodb
```

**Using MongoDB Atlas (Cloud):**
1. Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create a free account
3. Create a cluster
4. Get the connection string
5. Update `MONGODB_URI` in `.env`

### 7. Run the bot
```bash
python bot.py
```

## Usage

### In Private Chat
1. Start the bot with `/start`
2. Send a video file
3. Select quality (480p, 720p, 1080p)
4. Wait for compression
5. Receive compressed video in DM

### In Groups
1. Owner must authorize the group with `/auth`
2. Users can send videos
3. Select quality from buttons
4. Original video is deleted for security
5. Compressed video sent to user's DM

## Commands

### User Commands
| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/help` | Show help message |
| `/compress` | Compress video (interactive) |
| `/settings` | View 480p settings |
| `/settings1` | View 720p settings |
| `/settings2` | View 1080p settings |
| `/all` | Encode in all qualities |
| `/extract_audio` | Extract audio from video |
| `/addaudio` | Add audio to video |
| `/remaudio` | Remove audio from video |
| `/sub` | Add soft subtitles |
| `/hsub` | Add hard subtitles |
| `/rsub` | Remove all subtitles |
| `/trim` | Trim video |
| `/mediainfo` | Get media information |
| `/list` | Show active tasks |
| `/cancel` | Cancel a task |
| `/sysinfo` | System information |
| `/speedtest` | Network speed test |
| `/ping` | Check latency |

### Admin Commands
| Command | Description |
|---------|-------------|
| `/auth` | Authorize a group |
| `/deauth` | Deauthorize a group |
| `/restart` | Restart the bot |
| `/update` | Update from git |
| `/log` | Get bot logs |
| `/stats` | View bot statistics |
| `/broadcast` | Broadcast message to all users |

## Encoding Settings

### 480p
- Resolution: 854x480
- Video Bitrate: 1 Mbps
- Audio Bitrate: 128 kbps
- CRF: 28
- FPS: 30

### 720p
- Resolution: 1280x720
- Video Bitrate: 2.5 Mbps
- Audio Bitrate: 192 kbps
- CRF: 23
- FPS: 30

### 1080p
- Resolution: 1920x1080
- Video Bitrate: 5 Mbps
- Audio Bitrate: 256 kbps
- CRF: 20
- FPS: 30

## File Structure

```
video-compressor-bot/
|-- bot.py              # Main bot file
|-- config.py           # Configuration settings
|-- database.py         # MongoDB operations
|-- encoder.py          # Video encoding functions
|-- utils.py            # Utility functions
|-- requirements.txt    # Python dependencies
|-- .env.example        # Environment template
|-- .env                # Your configuration (not in git)
|-- logs/
|   |-- bot.log         # Bot logs
|-- downloads/
    |-- videos/         # Downloaded videos
    |-- audio/          # Audio files
    |-- output/         # Compressed videos
    |-- temp/           # Temporary files
    |-- subtitles/      # Subtitle files
```

## Deployment

### Using Docker

Create a `Dockerfile`:
```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install FFmpeg
RUN apt update && apt install -y ffmpeg

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot files
COPY . .

# Run bot
CMD ["python", "bot.py"]
```

Build and run:
```bash
docker build -t video-compressor-bot .
docker run -d --env-file .env video-compressor-bot
```

### Using systemd (Linux)

Create `/etc/systemd/system/video-compressor.service`:
```ini
[Unit]
Description=Video Compressor Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/video-compressor-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable video-compressor
sudo systemctl start video-compressor
```

## Troubleshooting

### FFmpeg not found
Make sure FFmpeg is installed and in your PATH:
```bash
ffmpeg -version
```

### MongoDB connection error
- Check if MongoDB is running
- Verify connection string in `.env`
- Check firewall settings

### Bot not responding
- Check if bot token is correct
- Verify API ID and Hash
- Check logs in `logs/bot.log`

### Video compression fails
- Check available disk space
- Verify FFmpeg installation
- Check video file format

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License.

## Credits

- **Developer:** Shivam Bot Updates
- **Framework:** [Pyrogram](https://github.com/pyrogram/pyrogram)
- **Video Processing:** [FFmpeg](https://ffmpeg.org/)

## Support

For support, join [@ShivamBotUpdates](https://t.me/ShivamBotUpdates)