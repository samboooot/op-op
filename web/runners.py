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
        "sell_shares": run_sell_shares
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
    logger(f"📌 Topic ID: {topic_id}")
    
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
    
    logger(f"🎯 Outcome: {outcome.get('title')}")
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
                    
                    # Place sell order
                    best_ask = get_best_ask(orderbook)
                    
                    if best_ask:
                        shares = order["shares"] - order["sold_shares"]
                        if spread_mode:
                            sell_price = round(best_ask[0] - 0.001, 3)
                            best_bid = get_best_bid(orderbook)
                            if best_bid and sell_price <= best_bid[0]:
                                sell_price = best_ask[0]
                        else:
                            sell_price = best_ask[0]
                        
                        if shares * sell_price >= 1.0:
                            try:
                                token_id = yes_token_id if side == "yes" else no_token_id
                                logger(f"📤 Placing SELL {side.upper()} @ {sell_price}")
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
                
                # ===== BUY PRICE ADJUSTMENT CHECK =====
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
                                logger(f"   ⚠️ Remaining amount < $1, removing order")
                                del orders[key]
                        except Exception as e:
                            logger(f"   ❌ Reorder failed: {e}")
                            del orders[key]
                
                # ===== SELL PRICE ADJUSTMENT CHECK =====
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
                                logger(f"   ⚠️ Remaining amount < $1, removing order")
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
    
    # Cleanup - cancel remaining orders on stop
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
