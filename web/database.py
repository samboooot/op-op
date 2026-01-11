"""
Opinion.trade Dashboard - Database Module

SQLite database for storing trades and task history.
"""

import sqlite3
import os
from datetime import datetime
from typing import Dict, List, Optional
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'trades.db')


def init_db():
    """Initialize database with tables"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                task_id TEXT,
                event_name TEXT,
                outcome_name TEXT,
                side TEXT,
                action TEXT,
                price REAL,
                shares REAL,
                amount_usdt REAL,
                order_id INTEGER,
                mode TEXT,
                status TEXT DEFAULT 'open',
                profit_usdt REAL,
                notes TEXT
            )
        ''')
        
        # Tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                config TEXT,
                created_at TEXT,
                started_at TEXT,
                stopped_at TEXT,
                error TEXT
            )
        ''')
        
        # Logs table (for persistence)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                timestamp TEXT,
                level TEXT,
                message TEXT
            )
        ''')
        
        conn.commit()


@contextmanager
def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ==================== TRADES ====================

def add_trade(
    task_id: str,
    event_name: str,
    outcome_name: str,
    side: str,
    action: str,
    price: float,
    shares: float,
    amount_usdt: float,
    order_id: int,
    mode: str = "standard",
    status: str = "open"
) -> int:
    """Add a new trade record"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO trades 
            (timestamp, task_id, event_name, outcome_name, side, action, price, shares, amount_usdt, order_id, mode, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            task_id, event_name, outcome_name, side, action,
            price, shares, amount_usdt, order_id, mode, status
        ))
        conn.commit()
        return cursor.lastrowid


def update_trade_status(order_id: int, status: str, profit_usdt: float = None):
    """Update trade status"""
    with get_connection() as conn:
        cursor = conn.cursor()
        if profit_usdt is not None:
            cursor.execute(
                'UPDATE trades SET status = ?, profit_usdt = ? WHERE order_id = ?',
                (status, profit_usdt, order_id)
            )
        else:
            cursor.execute(
                'UPDATE trades SET status = ? WHERE order_id = ?',
                (status, order_id)
            )
        conn.commit()


def get_trades(limit: int = 100, offset: int = 0) -> List[Dict]:
    """Get recent trades"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM trades ORDER BY id DESC LIMIT ? OFFSET ?',
            (limit, offset)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_trade_stats() -> Dict:
    """Get trade statistics"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) as total FROM trades')
        total = cursor.fetchone()['total']
        
        cursor.execute('SELECT SUM(profit_usdt) as total_profit FROM trades WHERE profit_usdt IS NOT NULL')
        profit = cursor.fetchone()['total_profit'] or 0
        
        cursor.execute('SELECT COUNT(*) as wins FROM trades WHERE profit_usdt > 0')
        wins = cursor.fetchone()['wins']
        
        return {
            "total_trades": total,
            "total_profit": round(profit, 2),
            "wins": wins,
            "losses": total - wins if total > 0 else 0
        }


# ==================== TASKS ====================

def add_task(task_id: str, task_type: str, config: str) -> str:
    """Add a new task"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tasks (id, type, config, created_at)
            VALUES (?, ?, ?, ?)
        ''', (task_id, task_type, config, datetime.now().isoformat()))
        conn.commit()
        return task_id


def update_task_status(task_id: str, status: str, error: str = None):
    """Update task status"""
    with get_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        if status == 'running':
            cursor.execute(
                'UPDATE tasks SET status = ?, started_at = ? WHERE id = ?',
                (status, now, task_id)
            )
        elif status in ('stopped', 'completed', 'error'):
            cursor.execute(
                'UPDATE tasks SET status = ?, stopped_at = ?, error = ? WHERE id = ?',
                (status, now, error, task_id)
            )
        else:
            cursor.execute(
                'UPDATE tasks SET status = ? WHERE id = ?',
                (status, task_id)
            )
        conn.commit()


def get_tasks(limit: int = 50) -> List[Dict]:
    """Get recent tasks"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?',
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]


# ==================== LOGS ====================

def add_log(task_id: str, level: str, message: str):
    """Add a log entry"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO logs (task_id, timestamp, level, message)
            VALUES (?, ?, ?, ?)
        ''', (task_id, datetime.now().isoformat(), level, message))
        conn.commit()


def get_logs(task_id: str, limit: int = 200) -> List[Dict]:
    """Get logs for a task"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM logs WHERE task_id = ? ORDER BY id DESC LIMIT ?',
            (task_id, limit)
        )
        return [dict(row) for row in cursor.fetchall()][::-1]  # Reverse to chronological


# Initialize on import
init_db()
