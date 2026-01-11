"""
Управление задачами в памяти
"""

import threading
import uuid
import json
import time
from datetime import datetime
from typing import Dict, Callable, Optional, List
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Task:
    id: str
    type: str  # "market_maker" or "sell_shares"
    config: Dict
    status: TaskStatus = TaskStatus.PENDING
    thread: Optional[threading.Thread] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None


class TaskManager:
    """Manages bot tasks"""
    
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.log_callbacks: Dict[str, List[Callable]] = {}  # task_id -> callbacks
        self._lock = threading.RLock()  # Use RLock to allow recursive locking
    
    def create_task(self, task_type: str, config: Dict) -> str:
        """Create a new task"""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        
        task = Task(
            id=task_id,
            type=task_type,
            config=config
        )
        
        with self._lock:
            self.tasks[task_id] = task
        
        return task_id
    
    def start_task(self, task_id: str, runner: Callable) -> bool:
        """Start a task """
        print(f"[TASK_MANAGER] start_task called for {task_id}")
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.status != TaskStatus.PENDING:
                print(f"[TASK_MANAGER] Task not found or not pending: {task}")
                return False
            
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now().isoformat()
            task.stop_event.clear()
        
        def wrapped_runner():
            print(f"[TASK_MANAGER] Runner starting for {task_id}")
            try:
                runner(task_id, task.config, task.stop_event, self._create_logger(task_id))
                print(f"[TASK_MANAGER] Runner completed for {task_id}")
                with self._lock:
                    if task.status == TaskStatus.STOPPING:
                        task.status = TaskStatus.STOPPED
                    else:
                        task.status = TaskStatus.COMPLETED
            except Exception as e:
                print(f"[TASK_MANAGER] Runner error for {task_id}: {e}")
                import traceback
                traceback.print_exc()
                with self._lock:
                    task.status = TaskStatus.ERROR
                    task.error = str(e)
                self._log(task_id, "ERROR", f"Task error: {e}")
            finally:
                task.stopped_at = datetime.now().isoformat()
        
        task.thread = threading.Thread(target=wrapped_runner, daemon=True)
        task.thread.start()
        print(f"[TASK_MANAGER] Thread started for {task_id}")
        
        return True
    
    def stop_task(self, task_id: str) -> bool:
        """Signal task to stop"""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.status != TaskStatus.RUNNING:
                return False
            
            task.status = TaskStatus.STOPPING
            task.stop_event.set()
        
        return True
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """Get task info"""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            
            return {
                "id": task.id,
                "type": task.type,
                "config": task.config,
                "status": task.status.value,
                "error": task.error,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "stopped_at": task.stopped_at,
                "log_count": len(task.logs)
            }
    
    def get_all_tasks(self) -> List[Dict]:
        """Get all tasks"""
        with self._lock:
            return [self.get_task(tid) for tid in self.tasks.keys()]
    
    def get_running_tasks(self) -> List[Dict]:
        """Get running tasks only"""
        with self._lock:
            return [
                self.get_task(tid) 
                for tid, task in self.tasks.items() 
                if task.status == TaskStatus.RUNNING
            ]
    
    def get_task_logs(self, task_id: str, limit: int = 500) -> List[str]:
        """Get task logs"""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return []
            return task.logs[-limit:]
    
    def subscribe_logs(self, task_id: str, callback: Callable):
        """Subscribe to task logs"""
        with self._lock:
            if task_id not in self.log_callbacks:
                self.log_callbacks[task_id] = []
            self.log_callbacks[task_id].append(callback)
    
    def unsubscribe_logs(self, task_id: str, callback: Callable):
        """Unsubscribe from task logs"""
        with self._lock:
            if task_id in self.log_callbacks:
                try:
                    self.log_callbacks[task_id].remove(callback)
                except ValueError:
                    pass
    
    def _create_logger(self, task_id: str) -> Callable:
        """Create a logger function for a task"""
        def logger(message: str, level: str = "INFO"):
            self._log(task_id, level, message)
        return logger
    
    def _log(self, task_id: str, level: str, message: str):
        """Add log message and notify subscribers"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.logs.append(log_entry)
                # Keep only last 5000 logs in memory
                if len(task.logs) > 5000:
                    task.logs = task.logs[-5000:]
            
            callbacks = self.log_callbacks.get(task_id, []).copy()
        
        for callback in callbacks:
            try:
                callback(log_entry)
            except:
                pass


# Global task manager instance
task_manager = TaskManager()
