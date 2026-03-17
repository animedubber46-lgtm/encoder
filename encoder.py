import os
import re
import asyncio
import subprocess
import json
from typing import Optional, Dict, Tuple, Callable
from datetime import datetime
from config import PRESETS, FFMPEG_PATH, FFPROBE_PATH, MAX_FILE_SIZE


class VideoEncoder:
    def __init__(self):
        self.active_processes = {}
        self.cancelled_tasks = set()

    @staticmethod
    async def get_video_info(file_path: str) -> Optional[Dict]:
        """Get video information using ffprobe"""
        try:
            cmd = [
                FFPROBE_PATH, "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", file_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                data = json.loads(stdout.decode())
                
                video_stream = None
                audio_stream = None
                subtitle_stream = None
                
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video" and not video_stream:
                        video_stream = stream
                    elif stream.get("codec_type") == "audio" and not audio_stream:
                        audio_stream = stream
                    elif stream.get("codec_type") == "subtitle" and not subtitle_stream:
                        subtitle_stream = stream
                
                format_info = data.get("format", {})
                
                return {
                    "duration": float(format_info.get("duration", 0)),
                    "size": int(format_info.get("size", 0)),
                    "bit_rate": int(format_info.get("bit_rate", 0)),
                    "format": format_info.get("format_name", ""),
                    "video": {
                        "width": video_stream.get("width", 0) if video_stream else 0,
                        "height": video_stream.get("height", 0) if video_stream else 0,
                        "codec": video_stream.get("codec_name", "") if video_stream else "",
                        "fps": eval(video_stream.get("r_frame_rate", "0/1")) if video_stream else 0,
                        "bit_rate": int(video_stream.get("bit_rate", 0)) if video_stream else 0
                    } if video_stream else None,
                    "audio": {
                        "codec": audio_stream.get("codec_name", "") if audio_stream else "",
                        "sample_rate": int(audio_stream.get("sample_rate", 0)) if audio_stream else 0,
                        "channels": audio_stream.get("channels", 0) if audio_stream else 0,
                        "bit_rate": int(audio_stream.get("bit_rate", 0)) if audio_stream else 0
                    } if audio_stream else None,
                    "has_subtitle": subtitle_stream is not None
                }
        except Exception as e:
            print(f"Error getting video info: {e}")
        return None

    @staticmethod
    async def get_media_info(file_path: str) -> str:
        """Get detailed media info string"""
        info = await VideoEncoder.get_video_info(file_path)
        if not info:
            return "Unable to get media information"
        
        duration = info.get("duration", 0)
        hours, remainder = divmod(int(duration), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        size_mb = info.get("size", 0) / (1024 * 1024)
        bit_rate_mbps = info.get("bit_rate", 0) / (1024 * 1024)
        
        result = f"""
📹 **Media Information**

⏱ **Duration:** {hours:02d}:{minutes:02d}:{seconds:02d}
📦 **Size:** {size_mb:.2f} MB
📊 **Bitrate:** {bit_rate_mbps:.2f} Mbps
🎬 **Format:** {info.get('format', 'Unknown')}

"""
        video = info.get("video")
        if video:
            result += f"""🎥 **Video Stream:**
   • Resolution: {video.get('width')}x{video.get('height')}
   • Codec: {video.get('codec')}
   • FPS: {video.get('fps')}
   • Bitrate: {video.get('bit_rate') / 1000:.0f} kbps

"""
        
        audio = info.get("audio")
        if audio:
            result += f"""🔊 **Audio Stream:**
   • Codec: {audio.get('codec')}
   • Sample Rate: {audio.get('sample_rate')} Hz
   • Channels: {audio.get('channels')}
   • Bitrate: {audio.get('bit_rate') / 1000:.0f} kbps

"""
        
        result += f"📝 **Subtitles:** {'Yes' if info.get('has_subtitle') else 'No'}"
        return result

    def cancel_task(self, task_id: str):
        """Mark a task for cancellation"""
        self.cancelled_tasks.add(task_id)
        if task_id in self.active_processes:
            try:
                self.active_processes[task_id].terminate()
            except Exception:
                pass

    def is_cancelled(self, task_id: str) -> bool:
        """Check if task is cancelled"""
        return task_id in self.cancelled_tasks

    def clear_cancelled(self, task_id: str):
        """Clear cancelled status"""
        self.cancelled_tasks.discard(task_id)
        self.active_processes.pop(task_id, None)

    async def compress_video(
        self,
        input_path: str,
        output_path: str,
        quality: str,
        task_id: str,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[bool, str]:
        """Compress video with specified quality"""
        try:
            if self.is_cancelled(task_id):
                self.clear_cancelled(task_id)
                return False, "Task cancelled"
            
            preset = PRESETS.get(quality, PRESETS["720p"])
            video_info = await self.get_video_info(input_path)
            
            if not video_info or not video_info.get("video"):
                return False, "Invalid video file"
            
            # Build FFmpeg command
            cmd = [
                FFMPEG_PATH,
                "-i", input_path,
                "-y",  # Overwrite output
                "-c:v", "libx264",
                "-preset", preset["preset"],
                "-crf", str(preset["crf"]),
                "-maxrate", preset["video_bitrate"],
                "-bufsize", f"{int(preset['video_bitrate'].replace('M', '')) * 2}M",
                "-vf", f"scale={preset['resolution'].replace('x', ':')}:force_original_aspect_ratio=decrease,pad={preset['resolution'].replace('x', ':')}:(ow-iw)/2:(oh-ih)/2",
                "-r", str(preset["fps"]),
                "-c:a", "aac",
                "-b:a", preset["audio_bitrate"],
                "-movflags", "+faststart",
                output_path
            ]
            
            # Get duration for progress calculation
            duration = video_info.get("duration", 0)
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.active_processes[task_id] = process
            
            # Read stderr for progress
            last_progress = 0
            while True:
                if self.is_cancelled(task_id):
                    process.terminate()
                    self.clear_cancelled(task_id)
                    return False, "Task cancelled"
                
                line = await process.stderr.readline()
                if not line:
                    break
                
                line = line.decode('utf-8', errors='ignore')
                
                # Parse progress from ffmpeg output
                time_match = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", line)
                if time_match and duration > 0:
                    hours = int(time_match.group(1))
                    minutes = int(time_match.group(2))
                    seconds = float(time_match.group(3))
                    current_time = hours * 3600 + minutes * 60 + seconds
                    progress = min(int((current_time / duration) * 100), 99)
                    
                    if progress > last_progress and progress_callback:
                        last_progress = progress
                        await progress_callback(progress)
            
            await process.wait()
            self.clear_cancelled(task_id)
            
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    await progress_callback(100)
                return True, "Compression completed"
            else:
                return False, "Compression failed"
                
        except Exception as e:
            self.clear_cancelled(task_id)
            return False, f"Error: {str(e)}"

    async def compress_all_qualities(
        self,
        input_path: str,
        output_dir: str,
        base_name: str,
        task_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Tuple[bool, Dict[str, str]]:
        """Compress video in all qualities (480p, 720p, 1080p)"""
        results = {}
        qualities = ["480p", "720p", "1080p"]
        
        for i, quality in enumerate(qualities):
            if self.is_cancelled(task_id):
                self.clear_cancelled(task_id)
                return False, results
            
            output_path = os.path.join(output_dir, f"{base_name}_{quality}.mp4")
            
            async def quality_progress(p):
                overall_progress = ((i * 100) + p) // len(qualities)
                if progress_callback:
                    await progress_callback(overall_progress, quality)
            
            success, message = await self.compress_video(
                input_path, output_path, quality, task_id, quality_progress
            )
            
            if success:
                results[quality] = output_path
            else:
                results[quality] = None
        
        self.clear_cancelled(task_id)
        return True, results

    async def extract_audio(
        self,
        input_path: str,
        output_path: str,
        audio_format: str = "mp3",
        bitrate: str = "192k",
        task_id: str = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[bool, str]:
        """Extract audio from video"""
        try:
            if task_id and self.is_cancelled(task_id):
                self.clear_cancelled(task_id)
                return False, "Task cancelled"
            
            cmd = [
                FFMPEG_PATH,
                "-i", input_path,
                "-y",
                "-vn",
                "-acodec", "libmp3lame" if audio_format == "mp3" else "copy",
                "-b:a", bitrate,
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            if task_id:
                self.active_processes[task_id] = process
            
            await process.wait()
            
            if task_id:
                self.clear_cancelled(task_id)
            
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    await progress_callback(100)
                return True, "Audio extracted successfully"
            else:
                return False, "Audio extraction failed"
                
        except Exception as e:
            if task_id:
                self.clear_cancelled(task_id)
            return False, f"Error: {str(e)}"

    async def add_audio(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        task_id: str = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[bool, str]:
        """Add audio to video"""
        try:
            if task_id and self.is_cancelled(task_id):
                self.clear_cancelled(task_id)
                return False, "Task cancelled"
            
            cmd = [
                FFMPEG_PATH,
                "-i", video_path,
                "-i", audio_path,
                "-y",
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            if task_id:
                self.active_processes[task_id] = process
            
            await process.wait()
            
            if task_id:
                self.clear_cancelled(task_id)
            
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    await progress_callback(100)
                return True, "Audio added successfully"
            else:
                return False, "Failed to add audio"
                
        except Exception as e:
            if task_id:
                self.clear_cancelled(task_id)
            return False, f"Error: {str(e)}"

    async def remove_audio(
        self,
        input_path: str,
        output_path: str,
        task_id: str = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[bool, str]:
        """Remove audio from video"""
        try:
            if task_id and self.is_cancelled(task_id):
                self.clear_cancelled(task_id)
                return False, "Task cancelled"
            
            cmd = [
                FFMPEG_PATH,
                "-i", input_path,
                "-y",
                "-c:v", "copy",
                "-an",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            if task_id:
                self.active_processes[task_id] = process
            
            await process.wait()
            
            if task_id:
                self.clear_cancelled(task_id)
            
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    await progress_callback(100)
                return True, "Audio removed successfully"
            else:
                return False, "Failed to remove audio"
                
        except Exception as e:
            if task_id:
                self.clear_cancelled(task_id)
            return False, f"Error: {str(e)}"

    async def add_soft_subtitle(
        self,
        video_path: str,
        subtitle_path: str,
        output_path: str,
        language: str = "eng",
        task_id: str = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[bool, str]:
        """Add soft subtitle to video"""
        try:
            if task_id and self.is_cancelled(task_id):
                self.clear_cancelled(task_id)
                return False, "Task cancelled"
            
            cmd = [
                FFMPEG_PATH,
                "-i", video_path,
                "-i", subtitle_path,
                "-y",
                "-c:v", "copy",
                "-c:a", "copy",
                "-c:s", "mov_text",
                "-map", "0:v",
                "-map", "0:a?",
                "-map", "1:s",
                f"-metadata:s:s:0", f"language={language}",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            if task_id:
                self.active_processes[task_id] = process
            
            await process.wait()
            
            if task_id:
                self.clear_cancelled(task_id)
            
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    await progress_callback(100)
                return True, "Subtitle added successfully"
            else:
                return False, "Failed to add subtitle"
                
        except Exception as e:
            if task_id:
                self.clear_cancelled(task_id)
            return False, f"Error: {str(e)}"

    async def add_hard_subtitle(
        self,
        video_path: str,
        subtitle_path: str,
        output_path: str,
        task_id: str = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[bool, str]:
        """Add hard subtitle to video (burn in)"""
        try:
            if task_id and self.is_cancelled(task_id):
                self.clear_cancelled(task_id)
                return False, "Task cancelled"
            
            # Get video info for progress
            video_info = await self.get_video_info(video_path)
            duration = video_info.get("duration", 0) if video_info else 0
            
            # Escape subtitle path for ffmpeg
            sub_path = subtitle_path.replace("\\", "/").replace(":", "\\:")
            
            cmd = [
                FFMPEG_PATH,
                "-i", video_path,
                "-vf", f"subtitles='{sub_path}'",
                "-y",
                "-c:a", "copy",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            if task_id:
                self.active_processes[task_id] = process
            
            # Parse progress
            while True:
                if task_id and self.is_cancelled(task_id):
                    process.terminate()
                    self.clear_cancelled(task_id)
                    return False, "Task cancelled"
                
                line = await process.stderr.readline()
                if not line:
                    break
                
                line = line.decode('utf-8', errors='ignore')
                time_match = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", line)
                if time_match and duration > 0 and progress_callback:
                    hours = int(time_match.group(1))
                    minutes = int(time_match.group(2))
                    seconds = float(time_match.group(3))
                    current_time = hours * 3600 + minutes * 60 + seconds
                    progress = min(int((current_time / duration) * 100), 99)
                    await progress_callback(progress)
            
            await process.wait()
            
            if task_id:
                self.clear_cancelled(task_id)
            
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    await progress_callback(100)
                return True, "Hard subtitle added successfully"
            else:
                return False, "Failed to add hard subtitle"
                
        except Exception as e:
            if task_id:
                self.clear_cancelled(task_id)
            return False, f"Error: {str(e)}"

    async def remove_subtitles(
        self,
        input_path: str,
        output_path: str,
        task_id: str = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[bool, str]:
        """Remove all subtitles from video"""
        try:
            if task_id and self.is_cancelled(task_id):
                self.clear_cancelled(task_id)
                return False, "Task cancelled"
            
            cmd = [
                FFMPEG_PATH,
                "-i", input_path,
                "-y",
                "-c:v", "copy",
                "-c:a", "copy",
                "-sn",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            if task_id:
                self.active_processes[task_id] = process
            
            await process.wait()
            
            if task_id:
                self.clear_cancelled(task_id)
            
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    await progress_callback(100)
                return True, "Subtitles removed successfully"
            else:
                return False, "Failed to remove subtitles"
                
        except Exception as e:
            if task_id:
                self.clear_cancelled(task_id)
            return False, f"Error: {str(e)}"

    async def trim_video(
        self,
        input_path: str,
        output_path: str,
        start_time: str,
        end_time: str,
        task_id: str = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Tuple[bool, str]:
        """Trim video from start_time to end_time"""
        try:
            if task_id and self.is_cancelled(task_id):
                self.clear_cancelled(task_id)
                return False, "Task cancelled"
            
            cmd = [
                FFMPEG_PATH,
                "-i", input_path,
                "-ss", start_time,
                "-to", end_time,
                "-y",
                "-c:v", "libx264",
                "-c:a", "aac",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            if task_id:
                self.active_processes[task_id] = process
            
            await process.wait()
            
            if task_id:
                self.clear_cancelled(task_id)
            
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    await progress_callback(100)
                return True, "Video trimmed successfully"
            else:
                return False, "Failed to trim video"
                
        except Exception as e:
            if task_id:
                self.clear_cancelled(task_id)
            return False, f"Error: {str(e)}"


# Global encoder instance
encoder = VideoEncoder()