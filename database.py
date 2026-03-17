import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGODB_URI, DATABASE_NAME, OWNER_ID


class Database:
    def __init__(self):
        self.client = None
        self.db = None
        self.authorized_chats = None
        self.users = None
        self.tasks = None
        self._connected = False
        # In-memory fallback storage
        self._auth_chats_cache: Dict[int, Dict] = {}
        self._users_cache: Dict[int, Dict] = {}
        self._tasks_cache: Dict[str, Dict] = {}

    async def connect(self):
        """Connect to MongoDB"""
        try:
            self.client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            # Test connection
            await self.client.admin.command('ping')
            self.db = self.client[DATABASE_NAME]
            self.authorized_chats = self.db.authorized_chats
            self.users = self.db.users
            self.tasks = self.db.tasks
            
            # Create indexes
            try:
                await self.authorized_chats.create_index("chat_id", unique=True)
                await self.users.create_index("user_id", unique=True)
                await self.tasks.create_index("task_id", unique=True)
            except Exception:
                pass
            
            self._connected = True
            print("✅ Connected to MongoDB")
        except Exception as e:
            print(f"⚠️ MongoDB connection failed: {e}")
            print("📝 Using in-memory storage as fallback")
            self._connected = False

    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()

    # Authorization methods
    async def authorize_chat(self, chat_id: int, chat_title: str, authorized_by: int) -> bool:
        """Authorize a chat/group"""
        try:
            data = {
                "chat_id": chat_id,
                "chat_title": chat_title,
                "authorized_by": authorized_by,
                "authorized_at": datetime.now(),
                "is_active": True
            }
            if self._connected:
                await self.authorized_chats.insert_one(data)
            else:
                self._auth_chats_cache[chat_id] = data
            return True
        except Exception:
            return False

    async def deauthorize_chat(self, chat_id: int) -> bool:
        """Deauthorize a chat/group"""
        if self._connected:
            result = await self.authorized_chats.delete_one({"chat_id": chat_id})
            return result.deleted_count > 0
        else:
            if chat_id in self._auth_chats_cache:
                del self._auth_chats_cache[chat_id]
                return True
            return False

    async def is_chat_authorized(self, chat_id: int) -> bool:
        """Check if a chat is authorized"""
        # Owner's DM is always authorized
        if chat_id == OWNER_ID:
            return True
        
        if self._connected:
            chat = await self.authorized_chats.find_one({
                "chat_id": chat_id,
                "is_active": True
            })
            return chat is not None
        else:
            return chat_id in self._auth_chats_cache

    async def get_authorized_chats(self) -> List[Dict]:
        """Get all authorized chats"""
        if self._connected:
            chats = []
            async for chat in self.authorized_chats.find({"is_active": True}):
                chats.append(chat)
            return chats
        else:
            return list(self._auth_chats_cache.values())

    # User methods
    async def add_user(self, user_id: int, username: str, first_name: str) -> bool:
        """Add or update user"""
        try:
            data = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "last_seen": datetime.now(),
                "joined_at": datetime.now()
            }
            if self._connected:
                await self.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "username": username,
                            "first_name": first_name,
                            "last_seen": datetime.now()
                        },
                        "$setOnInsert": {
                            "joined_at": datetime.now()
                        }
                    },
                    upsert=True
                )
            else:
                if user_id not in self._users_cache:
                    self._users_cache[user_id] = data
                else:
                    self._users_cache[user_id].update(data)
            return True
        except Exception:
            return False

    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        if self._connected:
            return await self.users.find_one({"user_id": user_id})
        else:
            return self._users_cache.get(user_id)

    async def get_all_users(self) -> List[Dict]:
        """Get all users"""
        if self._connected:
            users = []
            async for user in self.users.find():
                users.append(user)
            return users
        else:
            return list(self._users_cache.values())

    async def get_users_count(self) -> int:
        """Get total users count"""
        if self._connected:
            return await self.users.count_documents({})
        else:
            return len(self._users_cache)

    # Task methods
    async def add_task(self, task_id: str, user_id: int, chat_id: int, 
                       message_id: int, file_name: str, quality: str,
                       task_type: str = "compress") -> bool:
        """Add a new task to queue"""
        try:
            data = {
                "task_id": task_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "file_name": file_name,
                "quality": quality,
                "task_type": task_type,
                "status": "pending",
                "progress": 0,
                "created_at": datetime.now(),
                "started_at": None,
                "completed_at": None
            }
            if self._connected:
                await self.tasks.insert_one(data)
            else:
                self._tasks_cache[task_id] = data
            return True
        except Exception:
            return False

    async def update_task_status(self, task_id: str, status: str, progress: int = 0) -> bool:
        """Update task status and progress"""
        update_data = {
            "status": status,
            "progress": progress
        }
        
        if status == "processing":
            update_data["started_at"] = datetime.now()
        elif status in ["completed", "failed", "cancelled"]:
            update_data["completed_at"] = datetime.now()
        
        if self._connected:
            result = await self.tasks.update_one(
                {"task_id": task_id},
                {"$set": update_data}
            )
            return result.modified_count > 0
        else:
            if task_id in self._tasks_cache:
                self._tasks_cache[task_id].update(update_data)
                return True
            return False

    async def get_task(self, task_id: str) -> Optional[Dict]:
        """Get task by ID"""
        if self._connected:
            return await self.tasks.find_one({"task_id": task_id})
        else:
            return self._tasks_cache.get(task_id)

    async def get_user_tasks(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get user's tasks"""
        if self._connected:
            tasks = []
            async for task in self.tasks.find({"user_id": user_id}).sort("created_at", -1).limit(limit):
                tasks.append(task)
            return tasks
        else:
            tasks = [t for t in self._tasks_cache.values() if t["user_id"] == user_id]
            return tasks[:limit]

    async def get_active_tasks(self) -> List[Dict]:
        """Get all active tasks"""
        if self._connected:
            tasks = []
            async for task in self.tasks.find({"status": {"$in": ["pending", "processing"]}}):
                tasks.append(task)
            return tasks
        else:
            return [t for t in self._tasks_cache.values() if t["status"] in ["pending", "processing"]]

    async def get_active_tasks_count(self) -> int:
        """Get count of active tasks"""
        if self._connected:
            return await self.tasks.count_documents({"status": {"$in": ["pending", "processing"]}})
        else:
            return len([t for t in self._tasks_cache.values() if t["status"] in ["pending", "processing"]])

    async def cancel_task(self, task_id: str, user_id: int) -> bool:
        """Cancel a task"""
        if self._connected:
            result = await self.tasks.update_one(
                {"task_id": task_id, "user_id": user_id, "status": {"$in": ["pending", "processing"]}},
                {"$set": {"status": "cancelled", "completed_at": datetime.now()}}
            )
            return result.modified_count > 0
        else:
            if task_id in self._tasks_cache and self._tasks_cache[task_id]["user_id"] == user_id:
                self._tasks_cache[task_id]["status"] = "cancelled"
                self._tasks_cache[task_id]["completed_at"] = datetime.now()
                return True
            return False

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task"""
        if self._connected:
            result = await self.tasks.delete_one({"task_id": task_id})
            return result.deleted_count > 0
        else:
            if task_id in self._tasks_cache:
                del self._tasks_cache[task_id]
                return True
            return False

    async def cleanup_old_tasks(self, days: int = 7) -> int:
        """Clean up tasks older than specified days"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        if self._connected:
            result = await self.tasks.delete_many({
                "status": {"$in": ["completed", "failed", "cancelled"]},
                "completed_at": {"$lt": cutoff}
            })
            return result.deleted_count
        else:
            count = 0
            to_delete = []
            for task_id, task in self._tasks_cache.items():
                if task["status"] in ["completed", "failed", "cancelled"]:
                    if task.get("completed_at") and task["completed_at"] < cutoff:
                        to_delete.append(task_id)
                        count += 1
            for task_id in to_delete:
                del self._tasks_cache[task_id]
            return count


# Global database instance
db = Database()
