"""
Логика ботов (Market Maker, Sell Shares)
"""

import os
import sys
import re
import time
import threading
from typing import Dict, Callable

# directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def get_runner(task_type: str) -> Callable:
    """Get runner function for task type"""
    runners = {
        "market_maker": run_market_maker,
        "sell_shares": run_sell_shares,
        "split_and_sell": run_split_and_sell
    }
    return runners.get(task_type)


# Global shared auth token 
_shared_auth_token: str = None
_token_lock = threading.Lock()


def set_shared_auth_token(token: str):
    """Update the auth token for all running tasks"""
    global _shared_auth_token
    with _token_lock:
        _shared_auth_token = token


def get_shared_auth_token() -> str:
    """Get the current auth token"""
    with _token_lock:
        return _shared_auth_token


def get_client(auth_token_override: str = None):
    """Create OpinionTradeClient """
    from opinion_client import OpinionTradeClient
    
    auth_token = auth_token_override or get_shared_auth_token() or os.getenv("AUTH_TOKEN")
    wallet = os.getenv("WALLET_ADDRESS")
    multisig = os.getenv("MULTISIG_ADDRESS")
    private_key = os.getenv("PRIVATE_KEY")
    
    if not all([auth_token, wallet, multisig, private_key]):
        raise ValueError("Missing (check Settings for auth token)")
    
    return OpinionTradeClient(auth_token, wallet, multisig, private_key)


def run_market_maker(
    task_id: str,
    config: Dict,
    stop_event: threading.Event,
    logger: Callable
):
    """
    Run market maker bot in headless mode
    
    Config:
        url: Event URL
        outcome: Outcome name
        amount: Amount USDT per side
        mode: "standard" or "spread"
        min_volume: Min order volume filter (default 5)
        interval: Poll interval seconds (default 5)
        single_order_side: "yes" or "no" to place only one side (optional)
        auth_token: Auth token 
    """
    # Get auth_token from config if provided
    auth_token_override = config.get("auth_token")
    
    try:
        client = get_client(auth_token_override)
    except Exception as e:
        logger(f"❌ {e}")
        return
    
    url = config.get("url")
    outcome_name = config.get("outcome")
    amount_usdt = float(config.get("amount", 15))
    spread_mode = config.get("mode") == "spread"
    min_volume = float(config.get("min_volume", 5))
    poll_interval = float(config.get("interval", 5))
    single_order_side = config.get("single_order_side")  # "yes", "no", or None
    
    logger(f"🚀 Starting Market Maker")
    logger(f"   URL: {url}")
    logger(f"   Outcome: {outcome_name}")
    logger(f"   Amount: {amount_usdt} USDT per side")
    logger(f"   Mode: {'SPREAD' if spread_mode else 'STANDARD'}")
    if single_order_side:
        logger(f"   Single Order: {single_order_side.upper()} only")
    
    # Parse URL
    match = re.search(r'topicId=(\d+)', url)
    if not match:
        logger("❌ Invalid URL: topicId not found")
        return
    
    topic_id = int(match.group(1))
    logger(f"Topic ID: {topic_id}")
    
    # Get outcome data
    try:
        topic_data = client.get_topic_data(topic_id)
        outcome = client.find_outcome(topic_data, outcome_name)
    except Exception as e:
        logger(f"❌ Failed to get outcome: {e}")
        return
    
    child_topic_id = outcome.get("topicId")
    yes_token_id = outcome.get("yesPos")
    no_token_id = outcome.get("noPos")
    question_id = outcome.get("questionId")
    
    logger(f"Section: {outcome.get('title')}")
    logger(f"   Child Topic ID: {child_topic_id}")
    
    # Get orderbook and place orders
    try:
        yes_orderbook = client.get_orderbook(question_id, yes_token_id, "yes")
        no_orderbook = client.get_orderbook(question_id, no_token_id, "no")
    except Exception as e:
        logger(f"❌ Failed to get orderbook: {e}")
        return
    
    # Filter and get best bid
    def get_best_bid(orderbook):
        bids = orderbook.get("bids", [])
        for bid in sorted(bids, key=lambda x: float(x[0]), reverse=True):
            price, volume = float(bid[0]), float(bid[1])
            if volume * price >= min_volume:
                return (price, volume)
        return None
    
    def get_best_ask(orderbook):
        asks = orderbook.get("asks", [])
        for ask in sorted(asks, key=lambda x: float(x[0])):
            price, volume = float(ask[0]), float(ask[1])
            if volume * price >= min_volume:
                return (price, volume)
        return None
    
    yes_best_bid = get_best_bid(yes_orderbook)
    no_best_bid = get_best_bid(no_orderbook)
    
    if not yes_best_bid or not no_best_bid:
        logger("❌ No valid prices with sufficient volume")
        return
    
    # Calculate prices
    if spread_mode:
        yes_buy_price = round(yes_best_bid[0] + 0.001, 3)
        no_buy_price = round(no_best_bid[0] + 0.001, 3)
        logger(f"📊 Spread mode: YES @ {yes_buy_price}, NO @ {no_buy_price}")
    else:
        yes_buy_price = yes_best_bid[0]
        no_buy_price = no_best_bid[0]
        logger(f"📊 Standard mode: YES @ {yes_buy_price}, NO @ {no_buy_price}")
    
    # Place orders
    orders = {}
    
    # Place YES order
    if single_order_side != "no":
        try:
            logger(f"📥 Placing BUY YES @ {yes_buy_price}")
            result = client.place_order(child_topic_id, yes_token_id, yes_buy_price, amount_usdt, "buy")
            order_data = result.get("orderData", {})
            orders["yes_buy"] = {
                "order_id": order_data.get("orderId"),
                "trans_no": order_data.get("transNo"),
                "price": yes_buy_price,
                "shares": amount_usdt / yes_buy_price,
                "sold_shares": 0
            }
            logger(f"   ✅ Order ID: {order_data.get('orderId')}")
        except Exception as e:
            logger(f"   ❌ Failed: {e}")
    
    # Place NO order
    if single_order_side != "yes":
        try:
            logger(f"📥 Placing BUY NO @ {no_buy_price}")
            result = client.place_order(child_topic_id, no_token_id, no_buy_price, amount_usdt, "buy")
            order_data = result.get("orderData", {})
            orders["no_buy"] = {
                "order_id": order_data.get("orderId"),
                "trans_no": order_data.get("transNo"),
                "price": no_buy_price,
                "shares": amount_usdt / no_buy_price,
                "sold_shares": 0
            }
            logger(f"   ✅ Order ID: {order_data.get('orderId')}")
        except Exception as e:
            logger(f"   ❌ Failed: {e}")
    
    if not orders:
        logger("❌ No orders placed, exiting")
        return
    
    # Monitoring loop
    logger("🔄 Starting monitoring...")
    iteration = 0
    last_status_log = time.time()  # For 5-minute status updates
    
    while not stop_event.is_set() and orders:
        iteration += 1
        
        try:
            # Get current data
            yes_orderbook = client.get_orderbook(question_id, yes_token_id, "yes")
            no_orderbook = client.get_orderbook(question_id, no_token_id, "no")
            open_orders = client.get_open_orders(topic_id)
            open_ids = {o.get("orderId") for o in open_orders}
            
            # Check each order
            for key in list(orders.keys()):
                order = orders[key]
                side = key.split("_")[0]  # "yes" or "no"
                orderbook = yes_orderbook if side == "yes" else no_orderbook
                order_type = order.get("type", "buy")
                
                if order["order_id"] not in open_ids:
                    # Order can be filled - VERIFY retries (can after sleep or network issues)
                    is_really_filled = True
                    for retry in range(3):
                        time.sleep(2)
                        try:
                            verify_orders = client.get_open_orders(topic_id)
                            verify_ids = {o.get("orderId") for o in verify_orders}
                            if order["order_id"] in verify_ids:
                                # Order still exists
                                logger(f"⚠️ {side.upper()} order still open (retry {retry+1}/3)")
                                is_really_filled = False
                                break
                        except Exception as e:
                            logger(f"⚠️ Verify retry {retry+1}/3 failed: {e}")
                            continue
                    
                    if not is_really_filled:
                        continue  # Skip, order not filled
                    
                    # Order confirmed filled!
                    if order_type == "sell":
                        logger(f"💰 {side.upper()} SELL filled! Order completed.")
                        del orders[key]
                        continue
                    
                    # BUY order filled - place sell order
                    logger(f"📦 {side.upper()} BUY filled!")
                    
                    # Get ACTUAL shares from positions (not calculated amount)
                    token_id = yes_token_id if side == "yes" else no_token_id
                    actual_shares = None
                    try:
                        positions = client.get_positions(topic_id)
                        for pos in positions:
                            if pos.get("tokenId") == token_id:
                                total = float(pos.get("tokenAmount", 0))
                                frozen = float(pos.get("tokenFrozenAmount", 0))
                                actual_shares = total - frozen
                                logger(f"   📊 Actual position: {actual_shares:.2f} shares")
                                break
                    except Exception as e:
                        logger(f"   ⚠️ Could not get positions: {e}")
                    
                    # Use actual shares or fallback to calculated
                    shares = actual_shares if actual_shares and actual_shares > 0 else (order["shares"] - order["sold_shares"])
                    
                    # Place sell order
                    best_ask = get_best_ask(orderbook)
                    
                    if best_ask and shares > 0:
                        if spread_mode:
                            sell_price = round(best_ask[0] - 0.001, 3)
                            best_bid = get_best_bid(orderbook)
                            if best_bid and sell_price <= best_bid[0]:
                                sell_price = best_ask[0]
                        else:
                            sell_price = best_ask[0]
                        
                        if shares * sell_price >= 1.0:
                            try:
                                logger(f"📤 Placing SELL {side.upper()} @ {sell_price} ({shares:.2f} shares)")
                                result = client.place_sell_shares(child_topic_id, token_id, sell_price, shares)
                                order_data = result.get("orderData", {})
                                logger(f"   ✅ Sell order placed, ID: {order_data.get('orderId')}")
                                
                                # Track sell order 
                                sell_key = f"{side}_sell"
                                orders[sell_key] = {
                                    "order_id": order_data.get("orderId"),
                                    "trans_no": order_data.get("transNo"),
                                    "price": sell_price,
                                    "shares": shares,
                                    "type": "sell"
                                }
                            except Exception as e:
                                logger(f"   ❌ Sell failed: {e}")
                    
                    del orders[key]
                    continue
                
                # ===== BUY PRICE CHECK =====
                if order.get("type", "buy") == "buy":
                    best_bid = get_best_bid(orderbook)
                    if best_bid and order["price"] < best_bid[0]:
                        # Someone placed a better bid 
                        old_price = order["price"]
                        new_price = best_bid[0]
                        
                        logger(f"🔄 Adjusting BUY {side.upper()}: {old_price} → {new_price}")
                        
                        # Cancel old order
                        try:
                            trans_no = order.get("trans_no")
                            if trans_no:
                                client.cancel_order(trans_no)
                                logger(f"   🗑️ Cancelled old order")
                        except Exception as e:
                            logger(f"   ⚠️ Cancel failed: {e}")
                        
                        time.sleep(0.5)
                        
                        # Place new order at better price
                        try:
                            remaining_shares = order["shares"] - order.get("sold_shares", 0)
                            remaining_usdt = remaining_shares * new_price
                            
                            if remaining_usdt >= 1.0:
                                token_id = yes_token_id if side == "yes" else no_token_id
                                logger(f"   📥 Placing new BUY {side.upper()} @ {new_price}")
                                result = client.place_order(child_topic_id, token_id, new_price, remaining_usdt, "buy")
                                order_data = result.get("orderData", {})
                                
                                # Update order info
                                order["order_id"] = order_data.get("orderId")
                                order["trans_no"] = order_data.get("transNo")
                                order["price"] = new_price
                                order["shares"] = remaining_usdt / new_price
                                
                                logger(f"   ✅ New Order ID: {order_data.get('orderId')}")
                            else:
                                logger(f"   ⚠️ Left amount < $1, removing order")
                                del orders[key]
                        except Exception as e:
                            logger(f"   ❌ Reorder failed: {e}")
                            del orders[key]
                
                # ===== SELL PRICE CHECK =====
                elif order.get("type") == "sell":
                    best_ask = get_best_ask(orderbook)
                    if best_ask and order["price"] > best_ask[0]:
                        # Someone placed a better ask with volume
                        old_price = order["price"]
                        new_price = best_ask[0]
                        
                        logger(f"🔄 Adjusting SELL {side.upper()}: {old_price} → {new_price}")
                        
                        # Cancel old order
                        try:
                            trans_no = order.get("trans_no")
                            if trans_no:
                                client.cancel_order(trans_no)
                                logger(f"   🗑️ Cancelled old order")
                        except Exception as e:
                            logger(f"   ⚠️ Cancel failed: {e}")
                        
                        time.sleep(0.5)
                        
                        # Place new sell order at better price
                        try:
                            shares = order["shares"]
                            if shares * new_price >= 1.0:
                                token_id = yes_token_id if side == "yes" else no_token_id
                                logger(f"   📤 Placing new SELL {side.upper()} @ {new_price}")
                                result = client.place_sell_shares(child_topic_id, token_id, new_price, shares)
                                order_data = result.get("orderData", {})
                                
                                # Update order info
                                order["order_id"] = order_data.get("orderId")
                                order["trans_no"] = order_data.get("transNo")
                                order["price"] = new_price
                                
                                logger(f"   ✅ New Order ID: {order_data.get('orderId')}")
                            else:
                                logger(f"   ⚠️ Left amount < $1, removing order")
                                del orders[key]
                        except Exception as e:
                            logger(f"   ❌ Reorder failed: {e}")
                            del orders[key]
            
            # Status update every 5 minutes
            current_time = time.time()
            if current_time - last_status_log >= 300:  # 5 minutes
                last_status_log = current_time
                
                # Build detailed order status
                order_details = []
                for key, order in orders.items():
                    side = key.split("_")[0].upper()  # "YES" or "NO"
                    orderbook = yes_orderbook if side == "YES" else no_orderbook
                    current_bid = get_best_bid(orderbook)
                    current_price = current_bid[0] if current_bid else "N/A"
                    total_shares = order["shares"]
                    sold_shares = order.get("sold_shares", 0)
                    fill_pct = int((sold_shares / total_shares) * 100) if total_shares > 0 else 0
                    value = round(total_shares * order["price"], 2)
                    order_details.append(f"{side}: {order['price']} (best: {current_price}, {fill_pct}%/${value})")
                
                if order_details:
                    logger(f"─── Status Update ───")
                    for detail in order_details:
                        logger(f"   📊 {detail}")
                else:
                    logger(f"─── Status Update | No active orders ───")
            
        except Exception as e:
            logger(f"⚠️ Error in loop: {e}")
        
        # Sleep with stop check
        for _ in range(int(poll_interval)):
            if stop_event.is_set():
                break
            time.sleep(1)
    
    # Cleanup
    logger("⛔ Stopping bot...")
    for key, order in orders.items():
        try:
            client.cancel_order(order["trans_no"])
            logger(f"   🗑️ Cancelled {key}")
        except:
            pass
    
    logger("✅ Market Maker stopped")


def run_sell_shares(
    task_id: str,
    config: Dict,
    stop_event: threading.Event,
    logger: Callable
):
    """
    Run sell shares 
    
    Config:
        topic_id: Optional parent topic ID
        mode: "standard" or "spread"
        min_volume: Min order volume (default 5)
    """
    try:
        client = get_client()
    except Exception as e:
        logger(f"❌ {e}")
        return
    
    parent_topic_id = config.get("topic_id")
    spread_mode = config.get("mode") == "spread"
    min_volume = float(config.get("min_volume", 5))
    poll_interval = float(config.get("interval", 5))
    
    logger(f"📤 Starting Sell Shares")
    logger(f"   Mode: {'SPREAD' if spread_mode else 'STANDARD'}")
    
    # Get positions
    try:
        positions = client.get_positions(parent_topic_id)
    except Exception as e:
        logger(f"❌ Failed to get positions: {e}")
        return
    
    # Filter positions
    to_sell = []
    for pos in positions:
        total = float(pos.get("tokenAmount", 0))
        frozen = float(pos.get("tokenFrozenAmount", 0))
        available = total - frozen
        last_price = float(pos.get("lastPrice", 0))
        
        if available > 0.01 and available * last_price >= 1.0:
            to_sell.append({
                "topic_id": pos.get("topicId"),
                "parent_topic_id": pos.get("mutilTopicId"),
                "title": pos.get("topicTitle", "Unknown"),
                "side": "YES" if pos.get("outcomeSide") == 1 else "NO",
                "shares": available,
                "token_id": pos.get("tokenId")
            })
    
    if not to_sell:
        logger("❌ No shares available to sell")
        return
    
    logger(f"💼 Found {len(to_sell)} positions")
    
    # Place sell orders
    sell_orders = {}
    
    for pos in to_sell:
        if stop_event.is_set():
            break
        
        # Get question_id
        try:
            topic_data = client.get_topic_data(pos["parent_topic_id"])
            question_id = None
            for child in topic_data.get("childList", []):
                if child.get("topicId") == pos["topic_id"]:
                    question_id = child.get("questionId")
                    break
            
            if not question_id:
                logger(f"   ⚠️ {pos['title']}: questionId not found")
                continue
            
            # Get orderbook
            orderbook = client.get_orderbook(question_id, pos["token_id"], pos["side"].lower())
            
            # Get best ask
            asks = orderbook.get("asks", [])
            best_ask = None
            for ask in sorted(asks, key=lambda x: float(x[0])):
                price, volume = float(ask[0]), float(ask[1])
                if volume * price >= min_volume:
                    best_ask = (price, volume)
                    break
            
            if not best_ask:
                logger(f"   ⚠️ {pos['title']}: no liquidity")
                continue
            
            if spread_mode:
                sell_price = round(best_ask[0] - 0.001, 3)
            else:
                sell_price = best_ask[0]
            
            logger(f"📤 SELL {pos['title']} ({pos['side']}) @ {sell_price}")
            result = client.place_sell_shares(pos["topic_id"], pos["token_id"], sell_price, pos["shares"])
            order_data = result.get("orderData", {})
            
            key = f"{pos['topic_id']}_{pos['side']}"
            sell_orders[key] = {
                "order_id": order_data.get("orderId"),
                "trans_no": order_data.get("transNo"),
                "title": pos["title"],
                "side": pos["side"],
                "price": sell_price,
                "shares": pos["shares"],
                "topic_id": pos["topic_id"],
                "parent_topic_id": pos["parent_topic_id"],
                "token_id": pos["token_id"],
                "question_id": question_id
            }
            logger(f"   ✅ Order ID: {order_data.get('orderId')}")
            
        except Exception as e:
            logger(f"   ❌ {pos['title']}: {e}")
    
    if not sell_orders:
        logger("❌ No sell orders placed")
        return
    
    # Monitor 
    logger("🔄 Starting monitoring...")
    iteration = 0
    last_status_log = time.time()  # For 5-minute status updates
    
    # Helper function for best ask
    def get_best_ask_for_order(order_info):
        try:
            orderbook = client.get_orderbook(order_info["question_id"], order_info["token_id"], order_info["side"].lower())
            asks = orderbook.get("asks", [])
            for ask in sorted(asks, key=lambda x: float(x[0])):
                price, volume = float(ask[0]), float(ask[1])
                if volume * price >= min_volume:
                    return price
        except:
            pass
        return None
    
    while not stop_event.is_set() and sell_orders:
        iteration += 1
        
        try:
            # Get open orders for checking
            open_orders = []
            for order in sell_orders.values():
                try:
                    orders_list = client.get_open_orders(order["parent_topic_id"])
                    open_orders.extend(orders_list)
                except:
                    pass
            open_ids = {o.get("orderId") for o in open_orders}
            
            # Check each order
            for key in list(sell_orders.keys()):
                order = sell_orders[key]
                
                if order["order_id"] not in open_ids:
                    # Order filled - VERIFY with retries
                    is_really_filled = True
                    for retry in range(3):
                        time.sleep(2)
                        try:
                            verify_orders = client.get_open_orders(order["parent_topic_id"])
                            verify_ids = {o.get("orderId") for o in verify_orders}
                            if order["order_id"] in verify_ids:
                                logger(f"⚠️ {order['title']} still open (retry {retry+1}/3)")
                                is_really_filled = False
                                break
                        except Exception as e:
                            logger(f"⚠️ Verify retry {retry+1}/3 failed: {e}")
                            continue
                    
                    if not is_really_filled:
                        continue
                    
                    # Confirmed filled!
                    logger(f"💰 {order['title']} ({order['side']}) SOLD!")
                    del sell_orders[key]
                    continue
                
                # Check if we need to adjust price
                best_ask = get_best_ask_for_order(order)
                if best_ask and order["price"] > best_ask:
                    # Someone placed a better ask 
                    old_price = order["price"]
                    new_price = best_ask
                    
                    logger(f"🔄 Adjusting {order['title']}: {old_price} → {new_price}")
                    
                    # Cancel old order
                    try:
                        if order["trans_no"]:
                            client.cancel_order(order["trans_no"])
                            logger(f"   🗑️ Cancelled old order")
                    except Exception as e:
                        logger(f"   ⚠️ Cancel failed: {e}")
                    
                    time.sleep(0.5)
                    
                    # Place new sell order
                    try:
                        if order["shares"] * new_price >= 1.0:
                            logger(f"   📤 Placing new SELL @ {new_price}")
                            result = client.place_sell_shares(order["topic_id"], order["token_id"], new_price, order["shares"])
                            order_data = result.get("orderData", {})
                            
                            order["order_id"] = order_data.get("orderId")
                            order["trans_no"] = order_data.get("transNo")
                            order["price"] = new_price
                            
                            logger(f"   ✅ New Order ID: {order_data.get('orderId')}")
                        else:
                            logger(f"   ⚠️ Value < $1, removing")
                            del sell_orders[key]
                    except Exception as e:
                        logger(f"   ❌ Reorder failed: {e}")
                        del sell_orders[key]
            
            # Status update every 5 minutes
            current_time = time.time()
            if current_time - last_status_log >= 300:  # 5 minutes
                last_status_log = current_time
                
                if sell_orders:
                    logger(f"─── Status Update ───")
                    for key, order in sell_orders.items():
                        best_ask = get_best_ask_for_order(order)
                        best_str = str(best_ask) if best_ask else "N/A"
                        value = round(order["shares"] * order["price"], 2)
                        logger(f"   📊 {order['side']}: {order['price']} (best: {best_str}, ${value})")
                else:
                    logger(f"─── Status Update | No active orders ───")
            
        except Exception as e:
            logger(f"⚠️ Error: {e}")
        
        # Sleep with stop check
        for _ in range(int(poll_interval)):
            if stop_event.is_set():
                break
            time.sleep(1)
    
    # Cleanup - cancel left orders on stop
    if stop_event.is_set() and sell_orders:
        logger("⛔ Stopping - cancelling orders...")
        for key, order in sell_orders.items():
            try:
                if order.get("trans_no"):
                    client.cancel_order(order["trans_no"])
                    logger(f"   🗑️ Cancelled: {order['title']}")
            except Exception as e:
                logger(f"   ⚠️ Failed to cancel {order['title']}: {e}")
    
    logger("✅ Sell Shares completed")


def run_split_and_sell(
    task_id: str,
    config: Dict,
    stop_event: threading.Event,
    logger: Callable
):
    """
    Run Split & Sell: convert USDT to YES+NO shares, then sell both
    
    Config:
        url: Event URL
        outcome: Outcome name
        amount: Amount USDT to split
        mode: "standard" or "spread"
        min_volume: Min order volume filter (default 5)
        interval: Poll interval seconds (default 5)
        sell_steps: Number of steps to sell (default 1)
        aggressive_mode: Sell expensive side more (default False)
        auth_token: Auth token override (optional)
    """
    auth_token_override = config.get("auth_token")
    
    try:
        client = get_client(auth_token_override)
    except Exception as e:
        logger(f"❌ {e}")
        return
    
    url = config.get("url")
    outcome_name = config.get("outcome")
    amount_usdt = float(config.get("amount", 10))
    spread_mode = config.get("mode") == "spread"
    min_volume = float(config.get("min_volume", 5))
    poll_interval = float(config.get("interval", 5))
    sell_steps = int(config.get("sell_steps", 1))
    aggressive_mode = config.get("aggressive_mode", False)
    
    logger(f"🔀 Starting Split & Sell")
    logger(f"   URL: {url}")
    logger(f"   Outcome: {outcome_name}")
    logger(f"   Amount: {amount_usdt} USDT")
    logger(f"   Mode: {'SPREAD' if spread_mode else 'STANDARD'}")
    logger(f"   Sell Steps: {sell_steps}")
    if aggressive_mode and sell_steps >= 2:
        logger(f"   Aggressive Mode: ON")
    
    # Parse URL
    match = re.search(r'topicId=(\d+)', url)
    if not match:
        logger("❌ Invalid URL: topicId not found")
        return
    
    topic_id = int(match.group(1))
    logger(f"Topic ID: {topic_id}")
    
    # Get outcome data
    try:
        topic_data = client.get_topic_data(topic_id)
        outcome = client.find_outcome(topic_data, outcome_name)
    except Exception as e:
        logger(f"❌ Failed to get outcome: {e}")
        return
    
    child_topic_id = outcome.get("topicId")
    yes_token_id = outcome.get("yesPos")
    no_token_id = outcome.get("noPos")
    question_id = outcome.get("questionId")
    condition_id = outcome.get("conditionId") or outcome.get("questionId")
    
    logger(f"Section: {outcome.get('title')}")
    logger(f"   Child Topic ID: {child_topic_id}")
    logger(f"   Condition ID: {condition_id[:20]}..." if condition_id else "   Condition ID: None")
    
    if stop_event.is_set():
        return
    
    # Execute Split
    logger(f"🔀 Start Split - {amount_usdt} USDT...")
    try:
        result = client.split_shares(child_topic_id, amount_usdt, condition_id)
        logger(f"   ✅ Split successful!")
    except Exception as e:
        logger(f"   ❌ Split failed: {e}")
        return
    
    # Wait to confirm 
    logger("   ⏳ Waiting for shares (up to 60s)...")
    yes_shares = 0
    no_shares = 0
    
    for wait_attempt in range(12):  # 12 * 5 = 60 seconds
        if stop_event.is_set():
            return
        
        time.sleep(5)
        
        try:
            positions = client.get_positions(topic_id)
            for pos in positions:
                if pos.get("tokenId") == yes_token_id:
                    total = float(pos.get("tokenAmount", 0))
                    frozen = float(pos.get("tokenFrozenAmount", 0))
                    yes_shares = total - frozen
                elif pos.get("tokenId") == no_token_id:
                    total = float(pos.get("tokenAmount", 0))
                    frozen = float(pos.get("tokenFrozenAmount", 0))
                    no_shares = total - frozen
            
            if yes_shares > 0.01 and no_shares > 0.01:
                logger(f"   ✅ Shares received after {(wait_attempt+1)*5}s")
                logger(f"   ⏳ Waiting 10s for blockchain confirmation...")
                time.sleep(10)
                break
        except Exception as e:
            logger(f"   ⚠️ Polling error: {e}")
    
    logger(f"   📊 YES shares: {yes_shares:.2f}")
    logger(f"   📊 NO shares: {no_shares:.2f}")
    
    if yes_shares < 0.01 and no_shares < 0.01:
        logger("❌ No shares to sell after 60s wait")
        return
    
    # Track total available shares
    total_yes_available = yes_shares
    total_no_available = no_shares
    
    # Statistics tracking
    stats = {
        "initial_usdt": amount_usdt,
        "initial_yes_shares": yes_shares,
        "initial_no_shares": no_shares,
        "steps": [],  # List of step
        "current_step": None  # Current step
    }
    
    # Helper functions
    def get_best_ask(orderbook):
        asks = orderbook.get("asks", [])
        for ask in sorted(asks, key=lambda x: float(x[0])):
            price, volume = float(ask[0]), float(ask[1])
            if volume * price >= min_volume:
                return (price, volume)
        return None
    
    def get_current_prices():
        """Get current YES and NO best ask prices"""
        try:
            yes_ob = client.get_orderbook(question_id, yes_token_id, "yes")
            no_ob = client.get_orderbook(question_id, no_token_id, "no")
            yes_ask = get_best_ask(yes_ob)
            no_ask = get_best_ask(no_ob)
            return (yes_ask[0] if yes_ask else 0.5, no_ask[0] if no_ask else 0.5)
        except:
            return (0.5, 0.5)
    
    def place_and_monitor_step(yes_to_sell, no_to_sell, step_num, total_steps):
        """Place orders and wait for both to fill"""
        logger(f"🔀 Step {step_num}/{total_steps}: Selling {yes_to_sell:.2f} YES + {no_to_sell:.2f} NO")
        
        # Initialize step stats
        step_stats = {
            "step": step_num,
            "yes_initial_shares": yes_to_sell,
            "no_initial_shares": no_to_sell,
            "yes_initial_price": 0,  # Price order was first placed
            "no_initial_price": 0,
            "yes_sold_shares": 0,
            "no_sold_shares": 0,
            "yes_usdt": 0,
            "no_usdt": 0,
            "yes_prices": [],  # List of actual prices sold
            "no_prices": []
        }
        stats["current_step"] = step_stats
        
        sell_orders = {}
        
        try:
            yes_orderbook = client.get_orderbook(question_id, yes_token_id, "yes")
            no_orderbook = client.get_orderbook(question_id, no_token_id, "no")
        except Exception as e:
            logger(f"   ❌ Failed to get orderbook: {e}")
            return False, yes_to_sell, no_to_sell
        
        # Place YES order with retry
        if yes_to_sell >= 0.01:
            best_ask = get_best_ask(yes_orderbook)
            if best_ask:
                sell_price = round(best_ask[0] - 0.001, 3) if spread_mode else best_ask[0]
                for attempt in range(2):  # Max 2 attempts
                    try:
                        logger(f"   🔀 SELL YES: {sell_price} ({yes_to_sell:.2f} shares)")
                        result = client.place_sell_shares(child_topic_id, yes_token_id, sell_price, yes_to_sell)
                        order_data = result.get("orderData", {})
                        sell_orders["yes"] = {
                            "order_id": order_data.get("orderId"),
                            "trans_no": order_data.get("transNo"),
                            "side": "yes",
                            "price": sell_price,
                            "shares": yes_to_sell,
                            "original_shares": yes_to_sell,
                            "token_id": yes_token_id
                        }
                        # Record initial price for stats
                        step_stats["yes_initial_price"] = sell_price
                        break  # Success
                    except Exception as e:
                        error_msg = str(e)
                        # Try to get more details
                        if hasattr(e, 'response') and e.response is not None:
                            try:
                                error_msg = f"{e} - {e.response.text}"
                            except:
                                pass
                        logger(f"   ❌ YES order failed: {error_msg}")
                        if attempt == 0:
                            logger(f"   ⏳ Retrying in 5s...")
                            time.sleep(5)
        
        # Place NO order with retry
        if no_to_sell >= 0.01:
            best_ask = get_best_ask(no_orderbook)
            if best_ask:
                sell_price = round(best_ask[0] - 0.001, 3) if spread_mode else best_ask[0]
                for attempt in range(2):  # Max 2 attempts
                    try:
                        logger(f"   🔀 SELL NO: {sell_price} ({no_to_sell:.2f} shares)")
                        result = client.place_sell_shares(child_topic_id, no_token_id, sell_price, no_to_sell)
                        order_data = result.get("orderData", {})
                        sell_orders["no"] = {
                            "order_id": order_data.get("orderId"),
                            "trans_no": order_data.get("transNo"),
                            "side": "no",
                            "price": sell_price,
                            "shares": no_to_sell,
                            "original_shares": no_to_sell,
                            "token_id": no_token_id
                        }
                        # Record initial price for stats
                        step_stats["no_initial_price"] = sell_price
                        break  # Success
                    except Exception as e:
                        error_msg = str(e)
                        if hasattr(e, 'response') and e.response is not None:
                            try:
                                error_msg = f"{e} - {e.response.text}"
                            except:
                                pass
                        logger(f"   ❌ NO order failed: {error_msg}")
                        if attempt == 0:
                            logger(f"   ⏳ Retrying in 5s...")
                            time.sleep(5)
        
        if not sell_orders:
            logger(f"   ⚠️ No orders placed in step {step_num}")
            return False, yes_to_sell, no_to_sell
        
        # Monitor fill
        logger(f"   🔄 Monitoring step {step_num}...")
        last_log = time.time()
        
        while not stop_event.is_set() and sell_orders:
            try:
                # Refresh auth token from storage
                current_token = get_shared_auth_token()
                if current_token:
                    client.update_auth_token(current_token)
                
                yes_orderbook = client.get_orderbook(question_id, yes_token_id, "yes")
                no_orderbook = client.get_orderbook(question_id, no_token_id, "no")
                open_orders = client.get_open_orders(topic_id)
                open_ids = {o.get("orderId") for o in open_orders}
                
                for key in list(sell_orders.keys()):
                    order = sell_orders[key]
                    orderbook = yes_orderbook if order["side"] == "yes" else no_orderbook
                    
                    # Check if filled
                    if order["order_id"] not in open_ids:
                        is_filled = True
                        for _ in range(3):
                            time.sleep(2)
                            verify = client.get_open_orders(topic_id)
                            if order["order_id"] in {o.get("orderId") for o in verify}:
                                is_filled = False
                                break
                        
                        if is_filled:
                            # Record statistics to current step
                            sold_shares = order['shares']
                            sold_usdt = sold_shares * order['price']
                            step_stats = stats['current_step']
                            if order['side'] == 'yes':
                                step_stats['yes_sold_shares'] += sold_shares
                                step_stats['yes_usdt'] += sold_usdt
                                step_stats['yes_prices'].append(order['price'])
                            else:
                                step_stats['no_sold_shares'] += sold_shares
                                step_stats['no_usdt'] += sold_usdt
                                step_stats['no_prices'].append(order['price'])
                            
                            logger(f"   💰 {order['side'].upper()} SOLD @ {order['price']} ({sold_shares:.2f} shares = ${sold_usdt:.2f})")
                            del sell_orders[key]
                            continue
                    
                    # Price re-change
                    best_ask = get_best_ask(orderbook)
                    bids = orderbook.get("bids", [])
                    best_bid = float(bids[0][0]) if bids else 0
                    best_bid_vol = float(bids[0][0]) * float(bids[0][1]) if bids else 0
                    best_ask_vol = best_ask[0] * best_ask[1] if best_ask else 0
                    
                    if best_ask and order["price"] > best_ask[0]:
                        new_price = best_ask[0]
                        
                        # Log for debugging
                        logger(f"   📊 {order['side'].upper()} orderbook: bid={best_bid:.3f} (${best_bid_vol:.1f}) / ask={best_ask[0]:.3f} (${best_ask_vol:.1f})")
                        
                        # Safe: new price is best bid 
                        if new_price <= best_bid:
                            safe_price = round(best_bid + 0.001, 3)
                            logger(f"   ⚠️ Price {new_price} <= bid {best_bid}, using safe price {safe_price}")
                            new_price = safe_price
                        
                        logger(f"   🔄 {order['side'].upper()}: {order['price']} → {new_price}")
                        
                        try:
                            if order["trans_no"]:
                                client.cancel_order(order["trans_no"])
                        except:
                            pass
                        
                        time.sleep(0.5)
                        
                        try:
                            result = client.place_sell_shares(
                                child_topic_id, order["token_id"], new_price, order["shares"]
                            )
                            order_data = result.get("orderData", {})
                            order["order_id"] = order_data.get("orderId")
                            order["trans_no"] = order_data.get("transNo")
                            order["price"] = new_price
                        except Exception as e:
                            logger(f"   ⚠️ Reorder failed: {e}")
                
                # Log every 10 minutes
                if time.time() - last_log >= 600:
                    last_log = time.time()
                    for order in sell_orders.values():
                        original = order.get('original_shares', order['shares'])
                        sold = original - order['shares']
                        logger(f"   ⏳ {order['side'].upper()}: {order['price']} (Best: {order['price']:.3f} {sold:.2f}/{original:.2f} shares) pending...")
                        
            except Exception as e:
                logger(f"   ⚠️ Error: {e}")
            
            for _ in range(int(poll_interval)):
                if stop_event.is_set():
                    # Cancel
                    for order in sell_orders.values():
                        try:
                            if order.get("trans_no"):
                                client.cancel_order(order["trans_no"])
                        except:
                            pass
                    return False, 0, 0
                time.sleep(1)
        
        # Save step stats to list
        stats['steps'].append(stats['current_step'])
        return True, 0, 0
    
    # Calculate per-step amounts
    if sell_steps <= 1:
        # Single step - sell everything
        place_and_monitor_step(total_yes_available, total_no_available, 1, 1)
    else:
        # Multi-step selling
        base_yes_per_step = total_yes_available / sell_steps
        base_no_per_step = total_no_available / sell_steps
        
        # Aggressive mode
        yes_multiplier = 1.0
        no_multiplier = 1.0
        
        if aggressive_mode and sell_steps >= 2:
            yes_price, no_price = get_current_prices()
            logger(f"📌 Current prices YES:{yes_price:.3f}, NO:{no_price:.3f}")
            
            if yes_price > no_price:
                # YES is more - sell more YES
                diff_pct = (yes_price - no_price) / yes_price

                factor = min(diff_pct * 0.5, 0.4)  # Max 40%
                yes_multiplier = 1 + factor
                no_multiplier = 1 - factor
                logger(f"   Aggressive YES:{yes_price:.3f} > NO:{no_price:.3f} - {diff_pct*100:.1f}%")
            else:
                # NO is more - sell more NO
                diff_pct = (no_price - yes_price) / no_price
                factor = min(diff_pct * 0.5, 0.4)
                no_multiplier = 1 + factor
                yes_multiplier = 1 - factor
                logger(f"   Aggressive: NO:{no_price:.3f} > YES:{yes_price:.3f} - {diff_pct*100:.1f}%")
            
            # Show step-by-step
            base_yes = total_yes_available / sell_steps
            base_no = total_no_available / sell_steps
            logger(f"   📋 Step:")
            for s in range(1, sell_steps + 1):
                if s == sell_steps:
                    # Last step shows
                    yes_step = total_yes_available - base_yes * yes_multiplier * (s - 1)
                    no_step = total_no_available - base_no * no_multiplier * (s - 1)
                else:
                    yes_step = base_yes * yes_multiplier
                    no_step = base_no * no_multiplier
                logger(f"      Step {s}: YES {yes_step:.2f} / NO {no_step:.2f}")
        
        yes_remaining = total_yes_available
        no_remaining = total_no_available
        
        for step in range(1, sell_steps + 1):
            if stop_event.is_set():
                break
            
            if step == sell_steps:
                # Last step - sell all
                yes_to_sell = yes_remaining
                no_to_sell = no_remaining
            else:
                yes_to_sell = min(base_yes_per_step * yes_multiplier, yes_remaining)
                no_to_sell = min(base_no_per_step * no_multiplier, no_remaining)
                
                # Check if next step empty
                next_yes_remaining = yes_remaining - yes_to_sell
                next_no_remaining = no_remaining - no_to_sell
                
                if step == sell_steps - 1:  # Pre-last step
                    # Check if last step empty
                    if next_yes_remaining < 0.01 and next_no_remaining >= 0.01:
                        # add NO to this step
                        no_to_sell += next_no_remaining
                        logger(f"   Merg NO to step {step} (YES exhausted)")
                    elif next_no_remaining < 0.01 and next_yes_remaining >= 0.01:
                        # add YES to this step
                        yes_to_sell += next_yes_remaining
                        logger(f"   Merg YES to step {step} (NO exhausted)")
            
            # Round to 2 decimals
            yes_to_sell = round(yes_to_sell, 2)
            no_to_sell = round(no_to_sell, 2)
            
            if yes_to_sell < 0.01 and no_to_sell < 0.01:
                logger(f"   ⚠️ Step {step}: Nothing to sell")
                break
            
            success, unsold_yes, unsold_no = place_and_monitor_step(
                yes_to_sell, no_to_sell, step, sell_steps
            )
            
            yes_remaining -= (yes_to_sell - unsold_yes)
            no_remaining -= (no_to_sell - unsold_no)
            
            if not success:
                logger(f"   ⚠️ Step {step} incomplete")
                break
            
            logger(f"   ✅ Step {step} complete! Remaining: {yes_remaining:.2f} YES, {no_remaining:.2f} NO")
            
            if yes_remaining < 0.01 and no_remaining < 0.01:
                break
    
    # Print final statistics
    logger("=" * 40)
    logger("📊 STATS")
    logger(f"   Initial: ${stats['initial_usdt']:.2f} USDT")
    logger("")
    
    total_yes_sold = 0
    total_no_sold = 0
    total_yes_usdt = 0
    total_no_usdt = 0
    
    for step_data in stats['steps']:
        step_num = step_data['step']
        
        # Calculate average prices
        yes_avg = sum(step_data['yes_prices']) / len(step_data['yes_prices']) if step_data['yes_prices'] else 0
        no_avg = sum(step_data['no_prices']) / len(step_data['no_prices']) if step_data['no_prices'] else 0
        
        logger(f"   Step {step_num}:")
        if step_data['yes_initial_shares'] > 0:
            logger(f"      YES {step_data['yes_initial_shares']:.2f} → sell {step_data['yes_initial_price']:.3f} (avg: {yes_avg:.3f} = ${step_data['yes_usdt']:.2f})")
        if step_data['no_initial_shares'] > 0:
            logger(f"      NO {step_data['no_initial_shares']:.2f} → sell {step_data['no_initial_price']:.3f} (avg: {no_avg:.3f} = ${step_data['no_usdt']:.2f})")
        
        total_yes_sold += step_data['yes_sold_shares']
        total_no_sold += step_data['no_sold_shares']
        total_yes_usdt += step_data['yes_usdt']
        total_no_usdt += step_data['no_usdt']
    
    logger("")
    total_received = total_yes_usdt + total_no_usdt
    profit_loss = total_received - stats['initial_usdt']
    profit_pct = (profit_loss / stats['initial_usdt'] * 100) if stats['initial_usdt'] > 0 else 0
    
    logger(f"   TOTAL SOLD:")
    logger(f"      YES: {total_yes_sold:.2f} shares → ${total_yes_usdt:.2f}")
    logger(f"      NO: {total_no_sold:.2f} shares → ${total_no_usdt:.2f}")
    logger(f"   Total received: ${total_received:.2f}")
    if profit_loss >= 0:
        logger(f"   ✅ Profit: +${profit_loss:.2f} (+{profit_pct:.1f}%)")
    else:
        logger(f"   ❌ Loss: ${profit_loss:.2f} ({profit_pct:.1f}%)")
    logger("=" * 40)
    logger("✅ Split & Sell completed")


