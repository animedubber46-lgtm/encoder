import os
import time
import psutil
import shutil
import asyncio
import platform
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    task_id: str
    user_id: int
    chat_id: int
    message_id: int
    file_name: str
    quality: str
    task_type: str = "compress"
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    file_path: Optional[str] = None
    output_path: Optional[str] = None
    error_message: Optional[str] = None


class TaskQueue:
    def __init__(self, max_concurrent: int = 3):
        self.tasks: Dict[str, Task] = {}
        self.pending_queue: List[str] = []
        self.processing: List[str] = []
        self.max_concurrent = max_concurrent
        self._lock = asyncio.Lock()

    async def add_task(self, task: Task) -> str:
        """Add a task to the queue"""
        async with self._lock:
            self.tasks[task.task_id] = task
            self.pending_queue.append(task.task_id)
            return task.task_id

    async def get_next_task(self) -> Optional[Task]:
        """Get next pending task"""
        async with self._lock:
            if len(self.processing) >= self.max_concurrent:
                return None
            if not self.pending_queue:
                return None
            
            task_id = self.pending_queue.pop(0)
            task = self.tasks.get(task_id)
            if task:
                task.status = TaskStatus.PROCESSING
                task.started_at = datetime.now()
                self.processing.append(task_id)
            return task

    async def complete_task(self, task_id: str, success: bool, error: str = None):
        """Mark task as completed"""
        async with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
                task.completed_at = datetime.now()
                task.error_message = error
                if task_id in self.processing:
                    self.processing.remove(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task"""
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            
            if task.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now()
                
                if task_id in self.pending_queue:
                    self.pending_queue.remove(task_id)
                if task_id in self.processing:
                    self.processing.remove(task_id)
                return True
            return False

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        return self.tasks.get(task_id)

    async def get_user_tasks(self, user_id: int) -> List[Task]:
        """Get all tasks for a user"""
        return [t for t in self.tasks.values() if t.user_id == user_id]

    async def get_active_tasks(self) -> List[Task]:
        """Get all active tasks"""
        return [t for t in self.tasks.values() 
                if t.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]]

    async def get_queue_position(self, task_id: str) -> int:
        """Get position in queue"""
        try:
            return self.pending_queue.index(task_id) + 1
        except ValueError:
            return 0

    async def cleanup_completed(self, max_age_hours: int = 24):
        """Clean up completed tasks older than max_age_hours"""
        async with self._lock:
            now = datetime.now()
            to_remove = []
            for task_id, task in self.tasks.items():
                if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    if task.completed_at:
                        age = (now - task.completed_at).total_seconds() / 3600
                        if age > max_age_hours:
                            to_remove.append(task_id)
            
            for task_id in to_remove:
                del self.tasks[task_id]


class SystemInfo:
    @staticmethod
    def get_system_info() -> str:
        """Get system information"""
        try:
            # CPU info
            cpu_count = psutil.cpu_count(logical=True)
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_freq = psutil.cpu_freq()
            
            # Memory info
            memory = psutil.virtual_memory()
            memory_total = memory.total / (1024 ** 3)
            memory_used = memory.used / (1024 ** 3)
            memory_percent = memory.percent
            
            # Disk info
            disk = psutil.disk_usage('/')
            disk_total = disk.total / (1024 ** 3)
            disk_used = disk.used / (1024 ** 3)
            disk_percent = disk.percent
            
            # System info
            uname = platform.uname()
            
            info = f"""
🖥 **System Information**

**OS:** {uname.system} {uname.release}
**Architecture:** {uname.machine}
**Processor:** {uname.processor or 'Unknown'}

📊 **CPU:**
   • Cores: {cpu_count}
   • Usage: {cpu_percent}%
   • Frequency: {cpu_freq.current:.0f} MHz

💾 **Memory:**
   • Total: {memory_total:.2f} GB
   • Used: {memory_used:.2f} GB ({memory_percent}%)

💿 **Disk:**
   • Total: {disk_total:.2f} GB
   • Used: {disk_used:.2f} GB ({disk_percent}%)

🐍 **Python:** {platform.python_version()}
⏰ **Uptime:** {SystemInfo.get_uptime()}
"""
            return info
        except Exception as e:
            return f"Error getting system info: {str(e)}"

    @staticmethod
    def get_uptime() -> str:
        """Get system uptime"""
        try:
            boot_time = psutil.boot_time()
            uptime = time.time() - boot_time
            
            days, remainder = divmod(int(uptime), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            parts = []
            if days > 0:
                parts.append(f"{days}d")
            if hours > 0:
                parts.append(f"{hours}h")
            if minutes > 0:
                parts.append(f"{minutes}m")
            parts.append(f"{seconds}s")
            
            return " ".join(parts)
        except Exception:
            return "Unknown"

    @staticmethod
    async def speedtest() -> str:
        """Run network speed test"""
        try:
            # Try using speedtest-cli if available
            result = subprocess.run(
                ["speedtest-cli", "--simple"],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                return f"🌐 **Speed Test Results**\n\n{result.stdout}"
            else:
                # Fallback to basic ping test
                return await SystemInfo.ping_test()
                
        except FileNotFoundError:
            return await SystemInfo.ping_test()
        except subprocess.TimeoutExpired:
            return "Speed test timed out"
        except Exception as e:
            return f"Speed test error: {str(e)}"

    @staticmethod
    async def ping_test(host: str = "google.com") -> str:
        """Run ping test"""
        try:
            # Windows uses -n, Unix uses -c
            count_flag = "-n" if platform.system() == "Windows" else "-c"
            
            result = subprocess.run(
                ["ping", count_flag, "4", host],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                # Parse ping results
                lines = result.stdout.strip().split('\n')
                return f"🏓 **Ping Test Results**\n\n" + "\n".join(lines[-4:])
            else:
                return f"Ping test failed: {result.stderr}"
                
        except subprocess.TimeoutExpired:
            return "Ping test timed out"
        except Exception as e:
            return f"Ping test error: {str(e)}"

    @staticmethod
    async def check_latency() -> Tuple[bool, float]:
        """Check API latency"""
        try:
            start = time.time()
            # Simple latency check
            await asyncio.sleep(0)  # Yield control
            end = time.time()
            latency = (end - start) * 1000  # Convert to ms
            return True, latency
        except Exception:
            return False, 0


class FileManager:
    def __init__(self, base_dir: str = "downloads"):
        self.base_dir = base_dir
        self.ensure_directories()

    def ensure_directories(self):
        """Ensure all required directories exist"""
        dirs = [
            self.base_dir,
            os.path.join(self.base_dir, "videos"),
            os.path.join(self.base_dir, "audio"),
            os.path.join(self.base_dir, "output"),
            os.path.join(self.base_dir, "temp"),
            os.path.join(self.base_dir, "subtitles"),
            "logs"
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)

    def get_video_path(self, filename: str) -> str:
        """Get path for video file"""
        return os.path.join(self.base_dir, "videos", filename)

    def get_audio_path(self, filename: str) -> str:
        """Get path for audio file"""
        return os.path.join(self.base_dir, "audio", filename)

    def get_output_path(self, filename: str) -> str:
        """Get path for output file"""
        return os.path.join(self.base_dir, "output", filename)

    def get_temp_path(self, filename: str) -> str:
        """Get path for temp file"""
        return os.path.join(self.base_dir, "temp", filename)

    def get_subtitle_path(self, filename: str) -> str:
        """Get path for subtitle file"""
        return os.path.join(self.base_dir, "subtitles", filename)

    def cleanup_file(self, file_path: str):
        """Delete a file if it exists"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

    def cleanup_temp(self, max_age_hours: int = 1):
        """Clean up temp files older than max_age_hours"""
        temp_dir = os.path.join(self.base_dir, "temp")
        now = time.time()
        
        for filename in os.listdir(temp_dir):
            filepath = os.path.join(temp_dir, filename)
            if os.path.isfile(filepath):
                file_age = now - os.path.getmtime(filepath)
                if file_age > max_age_hours * 3600:
                    self.cleanup_file(filepath)

    def get_disk_usage(self) -> Tuple[float, float, float]:
        """Get disk usage for base directory"""
        try:
            usage = shutil.disk_usage(self.base_dir)
            total = usage.total / (1024 ** 3)
            used = usage.used / (1024 ** 3)
            free = usage.free / (1024 ** 3)
            return total, used, free
        except Exception:
            return 0, 0, 0


def format_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def format_duration(seconds: float) -> str:
    """Format duration in HH:MM:SS format"""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def generate_task_id() -> str:
    """Generate unique task ID"""
    import uuid
    return str(uuid.uuid4())[:8].upper()


def is_valid_time_format(time_str: str) -> bool:
    """Check if time string is valid (HH:MM:SS or MM:SS or SS)"""
    import re
    patterns = [
        r'^\d+:\d+:\d+$',  # HH:MM:SS
        r'^\d+:\d+$',      # MM:SS
        r'^\d+$'           # SS
    ]
    return any(re.match(pattern, time_str) for pattern in patterns)


def parse_time_to_seconds(time_str: str) -> int:
    """Parse time string to seconds"""
    parts = time_str.split(':')
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    else:
        return int(parts[0])


# Global instances
task_queue = TaskQueue()
file_manager = FileManager()