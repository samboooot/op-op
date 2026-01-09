"""
FastAPI сервер (API endpoints)
"""

import os
import sys
import json
import asyncio
from typing import Dict, List, Set, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.task_manager import task_manager, TaskStatus
from web import database as db


# ==================== MODELS ====================

class TaskCreate(BaseModel):
    type: str  # "market_maker" or "sell_shares"
    config: Dict


class TaskResponse(BaseModel):
    id: str
    type: str
    status: str
    config: Dict
    error: str = None
    created_at: str
    started_at: str = None
    stopped_at: str = None


# ==================== WEBSOCKET MANAGER ====================

class ConnectionManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}  # task_id -> websockets
    
    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = set()
        self.active_connections[task_id].add(websocket)
    
    def disconnect(self, websocket: WebSocket, task_id: str):
        if task_id in self.active_connections:
            self.active_connections[task_id].discard(websocket)
    
    async def broadcast(self, task_id: str, message: str):
        if task_id in self.active_connections:
            for connection in self.active_connections[task_id].copy():
                try:
                    await connection.send_text(message)
                except:
                    self.active_connections[task_id].discard(connection)


manager = ConnectionManager()


# ==================== APP SETUP ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.init_db()
    yield
    # Shutdown
    pass


app = FastAPI(title="Opinion.trade Bot Dashboard", lifespan=lifespan)

# Static files
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


# ==================== ROUTES ====================

@app.get("/")
async def root():
    """Serve main page"""
    index_path = os.path.join(static_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Opinion.trade Bot Dashboard API"}


@app.get("/api/status")
async def get_status():
    """Get dashboard status"""
    running = task_manager.get_running_tasks()
    stats = db.get_trade_stats()
    
    return {
        "running_tasks": len(running),
        "total_trades": stats["total_trades"],
        "total_profit": stats["total_profit"]
    }


class UpdateTokenRequest(BaseModel):
    auth_token: str


@app.post("/api/settings/token")
async def update_auth_token(req: UpdateTokenRequest):
    """Update shared auth token for all running tasks"""
    from web.runners import set_shared_auth_token
    set_shared_auth_token(req.auth_token)
    return {"status": "ok", "message": "Auth token updated for all tasks"}


# ==================== PREVIEW API ====================

class PreviewRequest(BaseModel):
    url: str
    outcome: str
    amount: float = 15.0
    min_volume: float = 5.0
    auth_token: str = None  


@app.post("/api/preview")
async def preview_order(req: PreviewRequest):
    """Get orderbook prices for preview before placing orders"""
    import re
    
    # Parse URL
    match = re.search(r'topicId=(\d+)', req.url)
    if not match:
        raise HTTPException(status_code=400, detail="Invalid URL: topicId not found")
    
    topic_id = int(match.group(1))
    
    # Get client
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from opinion_client import OpinionTradeClient
    
    # Use auth_token from request 
    auth_token = req.auth_token if req.auth_token else os.getenv("AUTH_TOKEN")
    wallet = os.getenv("WALLET_ADDRESS")
    multisig = os.getenv("MULTISIG_ADDRESS")
    private_key = os.getenv("PRIVATE_KEY")
    
    if not all([auth_token, wallet, multisig, private_key]):
        raise HTTPException(status_code=400, detail="Missing credentials (check Settings for auth token)")
    
    client = OpinionTradeClient(auth_token, wallet, multisig, private_key)
    
    try:
        # Get outcome data
        topic_data = client.get_topic_data(topic_id)
        outcome = client.find_outcome(topic_data, req.outcome)
        
        child_topic_id = outcome.get("topicId")
        yes_token_id = outcome.get("yesPos")
        no_token_id = outcome.get("noPos")
        question_id = outcome.get("questionId")
        
        # Get orderbook
        yes_orderbook = client.get_orderbook(question_id, yes_token_id, "yes")
        no_orderbook = client.get_orderbook(question_id, no_token_id, "no")
        
        # Filter by min volume
        def get_best_bid(orderbook):
            bids = orderbook.get("bids", [])
            for bid in sorted(bids, key=lambda x: float(x[0]), reverse=True):
                price, volume = float(bid[0]), float(bid[1])
                if volume * price >= req.min_volume:
                    return price
            return None
        
        def get_best_ask(orderbook):
            asks = orderbook.get("asks", [])
            for ask in sorted(asks, key=lambda x: float(x[0])):
                price, volume = float(ask[0]), float(ask[1])
                if volume * price >= req.min_volume:
                    return price
            return None
        
        yes_bid = get_best_bid(yes_orderbook)
        yes_ask = get_best_ask(yes_orderbook)
        no_bid = get_best_bid(no_orderbook)
        no_ask = get_best_ask(no_orderbook)
        
        if not yes_bid or not no_bid:
            raise HTTPException(status_code=400, detail="No valid prices with sufficient volume")
        
        # Calculate spread prices
        yes_spread_buy = round(yes_bid + 0.001, 3) if yes_bid else None
        no_spread_buy = round(no_bid + 0.001, 3) if no_bid else None
        
        # Check if spread exists
        has_yes_spread = yes_ask and yes_spread_buy < yes_ask
        has_no_spread = no_ask and no_spread_buy < no_ask
        
        # Get top 5 levels for display
        def get_top_levels(orderbook, side, count=5):
            data = orderbook.get(side, [])
            if side == "bids":
                sorted_data = sorted(data, key=lambda x: float(x[0]), reverse=True)
            else:
                sorted_data = sorted(data, key=lambda x: float(x[0]))
            return [[str(x[0]), str(x[1])] for x in sorted_data[:count]]
        
        return {
            "outcome": outcome.get("title"),
            "topic_id": topic_id,
            "child_topic_id": child_topic_id,
            "yes": {
                "bid": yes_bid,
                "ask": yes_ask,
                "spread_buy": yes_spread_buy if has_yes_spread else None,
                "has_spread": has_yes_spread,
                "bids": get_top_levels(yes_orderbook, "bids"),
                "asks": get_top_levels(yes_orderbook, "asks")
            },
            "no": {
                "bid": no_bid,
                "ask": no_ask,
                "spread_buy": no_spread_buy if has_no_spread else None,
                "has_spread": has_no_spread,
                "bids": get_top_levels(no_orderbook, "bids"),
                "asks": get_top_levels(no_orderbook, "asks")
            },
            "amount": req.amount,
            "estimated_shares_yes": round(req.amount / yes_bid, 2) if yes_bid else 0,
            "estimated_shares_no": round(req.amount / no_bid, 2) if no_bid else 0
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get prices: {e}")


# ==================== POSITIONS API ====================

class PositionsRequest(BaseModel):
    topic_id: Optional[int] = None  # Optional filter by parent topic
    auth_token: Optional[str] = None  # Optional auth token 


@app.post("/api/positions")
async def get_positions(req: PositionsRequest):
    """Get user's available shares/positions"""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from opinion_client import OpinionTradeClient
    
    # Use auth_token from request 
    auth_token = req.auth_token if req.auth_token else os.getenv("AUTH_TOKEN")
    wallet = os.getenv("WALLET_ADDRESS")
    multisig = os.getenv("MULTISIG_ADDRESS")
    private_key = os.getenv("PRIVATE_KEY")
    
    if not all([auth_token, wallet, multisig, private_key]):
        raise HTTPException(status_code=400, detail="Missing credentials (check Settings for auth token)")
    
    client = OpinionTradeClient(auth_token, wallet, multisig, private_key)
    
    try:
        positions = client.get_positions(req.topic_id)
        
        # Filter and format positions
        result = []
        for pos in positions:
            total = float(pos.get("tokenAmount", 0))
            frozen = float(pos.get("tokenFrozenAmount", 0))
            available = total - frozen
            last_price = float(pos.get("lastPrice", 0))
            
            if available > 0.01 and available * last_price >= 1.0:
                result.append({
                    "topic_id": pos.get("topicId"),
                    "parent_topic_id": pos.get("mutilTopicId"),
                    "title": pos.get("topicTitle", "Unknown"),
                    "outcome": pos.get("childTopicTitle", "Unknown"),
                    "side": "YES" if pos.get("outcomeSide") == 1 else "NO",
                    "shares": round(available, 2),
                    "value": round(available * last_price, 2),
                    "last_price": last_price,
                    "token_id": pos.get("tokenId")
                })
        
        return {"positions": result, "total": len(result)}
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[DEBUG] Positions error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== TASKS API ====================

@app.get("/api/tasks")
async def get_tasks():
    """Get all tasks - merge in-memory and database"""
    # Get current in-memory tasks (running ones)
    memory_tasks = task_manager.get_all_tasks()
    memory_ids = {t["id"] for t in memory_tasks}
    
    # Get historical tasks from database
    db_tasks = db.get_tasks(100)
    
    # use in-memory for current tasks, DB for historical
    result = list(memory_tasks)  # Start with in-memory
    
    for db_task in db_tasks:
        if db_task["id"] not in memory_ids:
            # Parse config from JSON string
            config = {}
            if db_task.get("config"):
                try:
                    config = json.loads(db_task["config"])
                except:
                    pass
            
            result.append({
                "id": db_task["id"],
                "type": db_task["type"],
                "status": db_task["status"],
                "config": config,
                "created_at": db_task["created_at"],
                "started_at": db_task.get("started_at"),
                "stopped_at": db_task.get("stopped_at"),
                "error": db_task.get("error")
            })
    
    # Sort by created_at descending
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return result


@app.post("/api/tasks")
async def create_task(task: TaskCreate):
    """Create a new task"""
    print(f"[DEBUG] Creating task: type={task.type}, config={task.config}")
    task_id = task_manager.create_task(task.type, task.config)
    db.add_task(task_id, task.type, json.dumps(task.config))
    print(f"[DEBUG] Created task: {task_id}")
    return {"id": task_id, "status": "pending"}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """Get task details"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/tasks/{task_id}/start")
async def start_task(task_id: str):
    """Start a task"""
    print(f"[DEBUG] Starting task: {task_id}")
    task = task_manager.get_task(task_id)
    if not task:
        print(f"[DEBUG] Task not found: {task_id}")
        raise HTTPException(status_code=404, detail="Task not found")
    
    print(f"[DEBUG] Task found: {task}")
    
    # Import runners
    from web.runners import get_runner
    
    runner = get_runner(task["type"])
    if not runner:
        print(f"[DEBUG] Unknown task type: {task['type']}")
        raise HTTPException(status_code=400, detail=f"Unknown task type: {task['type']}")
    
    print(f"[DEBUG] Starting runner...")
    success = task_manager.start_task(task_id, runner)
    print(f"[DEBUG] Start result: {success}")
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start task")
    
    db.update_task_status(task_id, "running")
    return {"status": "running"}


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    """Stop a running task"""
    success = task_manager.stop_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Task not running")
    
    db.update_task_status(task_id, "stopped")
    return {"status": "stopping"}


@app.get("/api/tasks/{task_id}/logs")
async def get_task_logs(task_id: str, limit: int = 100):
    """Get task logs"""
    logs = task_manager.get_task_logs(task_id, limit)
    return {"logs": logs}


# ==================== TRADES API ====================

@app.get("/api/trades")
async def get_trades(limit: int = 100, offset: int = 0):
    """Get trade history"""
    trades = db.get_trades(limit, offset)
    return {"trades": trades}


@app.get("/api/trades/stats")
async def get_trade_stats():
    """Get trade statistics"""
    return db.get_trade_stats()


# ==================== WEBSOCKET ====================

@app.websocket("/ws/logs/{task_id}")
async def websocket_logs(websocket: WebSocket, task_id: str):
    """WebSocket for real-time task logs"""
    await manager.connect(websocket, task_id)
    
    # Send existing logs
    existing_logs = task_manager.get_task_logs(task_id)
    for log in existing_logs:
        try:
            await websocket.send_text(log)
        except:
            break
    
    # Create callback for new logs
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    
    def log_callback(message: str):
        try:
            asyncio.run_coroutine_threadsafe(
                manager.broadcast(task_id, message),
                loop
            )
        except Exception as e:
            print(f"WebSocket callback error: {e}")
    
    # Subscribe to logs
    task_manager.subscribe_logs(task_id, log_callback)
    
    try:
        while True:
            try:
                # Keep connection alive with timeout
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_text("heartbeat")
                except:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        task_manager.unsubscribe_logs(task_id, log_callback)
        manager.disconnect(websocket, task_id)


# ==================== MAIN ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
