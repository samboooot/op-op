"""
API клиент для Opinion.trade
"""

import os
import sys
import json
import time
import requests
from pathlib import Path
from decimal import Decimal
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_typed_data

load_dotenv()

API_BASE = "https://proxy.opinion.trade:8443/api/bsc/api"
CHAIN_ID = 56

# EIP-712 
DOMAIN = {
    "name": "OPINION CTF Exchange",
    "version": "1",
    "chainId": CHAIN_ID,
    "verifyingContract": "0x5f45344126d6488025b0b84a3a8189f2487a7246"
}

BASE_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "referer": "https://app.opinion.trade/",
    "origin": "https://app.opinion.trade",
    "x-device-kind": "web",
    "x-device-fingerprint": "f934e0cfe7cfe764a4f56359e0823724",
    "x-aws-waf-token": "",
}


class OpinionTradeClient:
    """API клиент  Opinion.trade"""
    
    def __init__(
        self,
        auth_token: str,
        wallet_address: str,
        multisig_address: str,
        private_key: str
    ):
        self.auth_token = auth_token
        self.wallet_address = wallet_address
        self.multisig_address = multisig_address
        self.private_key = private_key
        self.headers = self._get_headers()
    
    def _get_headers(self) -> dict:
        """Формирование заголовков с авторизацией"""
        headers = BASE_HEADERS.copy()
        headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers
    
    # ==================== ORDER MANAGEMENT ====================
    
    def get_my_orders(
        self,
        query_type: int = 1,
        parent_topic_id: Optional[int] = None,
        page: int = 1,
        limit: int = 50
    ) -> List[Dict]:
        """
        Получить  ордера
        
        Args:
            query_type: 1 = открытые ордера, 2 = история
            parent_topic_id: ID родительского топика (опционально)
            page: Номер страницы
            limit: Количество на странице
            
        Returns:
            Список ордеров
        """
        url = f"{API_BASE}/v2/order"
        params = {
            "page": page,
            "limit": limit,
            "walletAddress": self.wallet_address,
            "queryType": query_type
        }
        if parent_topic_id:
            params["parentTopicId"] = parent_topic_id
        
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errno") != 0:
            raise Exception(f"API Error: {data.get('errmsg')}")
        
        return data.get("result", {}).get("list") or []
    
    def get_open_orders(self, parent_topic_id: Optional[int] = None) -> List[Dict]:
        """Получить открытые ордера"""
        return self.get_my_orders(query_type=1, parent_topic_id=parent_topic_id)
    
    def get_order_history(self, parent_topic_id: Optional[int] = None) -> List[Dict]:
        """Получить историю ордеров"""
        return self.get_my_orders(query_type=2, parent_topic_id=parent_topic_id)
    
    def cancel_order(self, trans_no: str) -> bool:
        """
        Отменить ордер
        
        Args:
            trans_no: Transaction number ордера (из orderData.transNo)
            
        Returns:
            True если успешно
        """
        url = f"{API_BASE}/v1/order/cancel/order"
        payload = {
            "trans_no": trans_no,
            "chainId": CHAIN_ID
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errno") != 0:
            raise Exception(f"Cancel failed: {data.get('errmsg')}")
        
        return True
    
    # ==================== ORDERBOOK ====================
    
    def get_orderbook(
        self,
        question_id: str,
        symbol: str,
        side: str = "yes"
    ) -> Dict:
        """
        Получить ордербук
        
        Args:
            question_id: ID вопроса
            symbol: Token ID (yesPos или noPos)
            side: "yes" или "no"
            
        Returns:
            Dict с bids, asks, last_price
        """
        url = f"{API_BASE}/v2/order/market/depth"
        symbol_types = "0" if side.lower() == "yes" else "1"
        
        params = {
            "question_id": question_id,
            "symbol": symbol,
            "chainId": CHAIN_ID,
            "symbol_types": symbol_types
        }
        
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errno") != 0:
            raise Exception(f"API Error: {data.get('errmsg')}")
        
        return data.get("result", {})
    
    def get_best_price(
        self,
        orderbook: Dict,
        side: str,  # "bid" or "ask"
        min_volume: float = 5.0
    ) -> Optional[float]:
        """
        Получить лучшую цену с учётом минимального объёма
        
        Args:
            orderbook: Ордербук
            side: "bid" (покупка) или "ask" (продажа)
            min_volume: Минимальный объём в USDT
            
        Returns:
            Лучшая цена или None
        """
        orders = orderbook.get("bids" if side == "bid" else "asks", [])
        
        for order in orders:
            price = float(order[0])
            volume = float(order[1])
            volume_usdt = volume * price
            
            if volume_usdt >= min_volume:
                return price
        
        return None
    
    # ==================== TOPIC DATA ====================
    
    def get_topic_data(self, topic_id: int) -> Dict:
        """Получить данные топика"""
        url = f"{API_BASE}/v2/topic/mutil/{topic_id}"
        
        response = requests.get(url, headers=self.headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errno") != 0:
            raise Exception(f"API Error: {data.get('errmsg')}")
        
        return data.get("result", {}).get("data", {})
    
    def find_outcome(self, topic_data: Dict, outcome_name: str) -> Dict:
        """Найти исход по имени"""
        for child in topic_data.get("childList", []):
            title = child.get("title", "")
            if outcome_name.lower() in title.lower() or title.lower() in outcome_name.lower():
                return child
        
        available = [c.get("title") for c in topic_data.get("childList", [])]
        raise ValueError(f"Outcome '{outcome_name}' not found. Available: {available}")
    
    # ==================== ORDER PLACEMENT ====================
    
    def _to_wei(self, amount: Decimal) -> str:
        """Convert Decimal to Wei string (18 decimals)"""
        return str(int(amount * Decimal(10**18)))
    
    def _round_price(self, price: float) -> Decimal:
        """Round price to 3 decimal places using Decimal"""
        return Decimal(str(price)).quantize(Decimal('0.001'))
    
    def _create_order_signature(
        self,
        maker: str,
        signer: str,
        token_id: str,
        maker_amount: str,
        taker_amount: str,
        salt: str,
        side: int
    ) -> str:
        """Create EIP-712 signature for order"""
        
        order_types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Order": [
                {"name": "salt", "type": "uint256"},
                {"name": "maker", "type": "address"},
                {"name": "signer", "type": "address"},
                {"name": "taker", "type": "address"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "makerAmount", "type": "uint256"},
                {"name": "takerAmount", "type": "uint256"},
                {"name": "expiration", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "feeRateBps", "type": "uint256"},
                {"name": "side", "type": "uint8"},
                {"name": "signatureType", "type": "uint8"},
            ]
        }
        
        message = {
            "salt": int(salt),
            "maker": maker.lower(),
            "signer": signer.lower(),
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(token_id),
            "makerAmount": int(maker_amount),
            "takerAmount": int(taker_amount),
            "expiration": 0,
            "nonce": 0,
            "feeRateBps": 0,
            "side": side,
            "signatureType": 2,
        }
        
        signable = encode_typed_data(
            domain_data=DOMAIN,
            message_types={"Order": order_types["Order"]},
            message_data=message
        )
        
        account = Account.from_key(self.private_key)
        signed = account.sign_message(signable)
        
        return "0x" + signed.signature.hex()
    
    def place_order(
        self,
        topic_id: int,
        token_id: str,
        price: float,
        amount_usdt: float,
        side: str,  # "buy" or "sell"
        use_wallet_as_maker: bool = False
    ) -> Dict:
        """
        Разместить лимитный ордер
        
        Args:
            topic_id: ID топика (дочерний!)
            token_id: Token ID (yesPos или noPos)
            price: Цена 0.01-0.99
            amount_usdt: Сумма в USDT
            side: "buy" или "sell"
            use_wallet_as_maker: Использовать wallet как maker
            
        Returns:
            Ответ API с orderData
        """
        side_int = 0 if side.lower() == "buy" else 1
        
        # Use Decimal for all calculations 
        price_decimal = self._round_price(price)
        amount_decimal = Decimal(str(amount_usdt))
        
        # Calculate amounts using Decimal
        if side_int == 0:  # BUY
            maker_amount = self._to_wei(amount_decimal)
            taker_amount = self._to_wei(amount_decimal / price_decimal)
        else:  # SELL
            maker_amount = self._to_wei(amount_decimal / price_decimal)
            taker_amount = self._to_wei(amount_decimal)
        
        salt = str(int(time.time() * 1000))
        
        # Determine maker/signer
        if use_wallet_as_maker:
            maker_addr = self.wallet_address
            signer_addr = self.wallet_address
        else:
            maker_addr = self.multisig_address
            signer_addr = self.wallet_address
        
        # Create signature
        signature = self._create_order_signature(
            maker=maker_addr,
            signer=signer_addr,
            token_id=token_id,
            maker_amount=maker_amount,
            taker_amount=taker_amount,
            salt=salt,
            side=side_int
        )
        
        # Build payload - use rounded price string
        payload = {
            "topicId": topic_id,
            "contractAddress": "",
            "price": str(price_decimal),
            "tradingMethod": 2,
            "salt": salt,
            "maker": maker_addr.lower(),
            "signer": signer_addr,
            "taker": "0x" + "0" * 40,
            "tokenId": token_id,
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": "0",
            "nonce": "0",
            "feeRateBps": "0",
            "side": str(side_int),
            "signatureType": "2",
            "signature": signature,
            "timestamp": int(time.time()),
            "sign": signature,
            "safeRate": "0.05",
            "orderExpTime": "0",
            "currencyAddress": "0x55d398326f99059fF775485246999027B3197955",
            "chainId": CHAIN_ID
        }
        
        url = f"{API_BASE}/v2/order"
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errno") != 0:
            raise Exception(f"Order failed: {data.get('errmsg')}")
        
        return data.get("result", {})
    
    def place_sell_shares(
        self,
        topic_id: int,
        token_id: str,
        price: float,
        shares: float,
        use_wallet_as_maker: bool = False
    ) -> Dict:
        """
        Разместить SELL ордер по количеству shares
        
        Args:
            topic_id: ID топика (дочерний!)
            token_id: Token ID
            price: Цена продажи
            shares: Количество shares для продажи
        """
        # Use Decimal for precision
        price_decimal = self._round_price(price)
        shares_decimal = Decimal(str(shares))
        
        # SELL: maker gives shares, taker gives USDT
        maker_amount = self._to_wei(shares_decimal)
        taker_amount = self._to_wei(shares_decimal * price_decimal)
        
        salt = str(int(time.time() * 1000))
        
        if use_wallet_as_maker:
            maker_addr = self.wallet_address
            signer_addr = self.wallet_address
        else:
            maker_addr = self.multisig_address
            signer_addr = self.wallet_address
        
        signature = self._create_order_signature(
            maker=maker_addr,
            signer=signer_addr,
            token_id=token_id,
            maker_amount=maker_amount,
            taker_amount=taker_amount,
            salt=salt,
            side=1  # SELL
        )
        
        payload = {
            "topicId": topic_id,
            "contractAddress": "",
            "price": str(price_decimal),
            "tradingMethod": 2,
            "salt": salt,
            "maker": maker_addr.lower(),
            "signer": signer_addr,
            "taker": "0x" + "0" * 40,
            "tokenId": token_id,
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": "0",
            "nonce": "0",
            "feeRateBps": "0",
            "side": "1",
            "signatureType": "2",
            "signature": signature,
            "timestamp": int(time.time()),
            "sign": signature,
            "safeRate": "0.05",
            "orderExpTime": "0",
            "currencyAddress": "0x55d398326f99059fF775485246999027B3197955",
            "chainId": CHAIN_ID
        }
        
        url = f"{API_BASE}/v2/order"
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errno") != 0:
            raise Exception(f"Sell order failed: {data.get('errmsg')}")
        
        return data.get("result", {})
    
    # ==================== POSITIONS ====================
    
    def get_positions(self, parent_topic_id: Optional[int] = None) -> List[Dict]:
        """
        Получить позиции (shares)
        
        Args:
            parent_topic_id: ID родительского топика (опционально)
            
        Returns:
            Список позиций
        """
        url = f"{API_BASE}/v2/portfolio"
        params = {
            "page": 1,
            "limit": 100,
            "walletAddress": self.wallet_address
        }
        if parent_topic_id:
            params["parentTopicId"] = parent_topic_id
        
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("errno") != 0:
            raise Exception(f"API Error: {data.get('errmsg')}")
        
        return data.get("result", {}).get("list") or []


# ==================== CLI for testing ====================

def main():
    """Test client functions"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Opinion.trade API Client")
    parser.add_argument("command", choices=["orders", "cancel", "positions"])
    parser.add_argument("--trans-no", help="Transaction number for cancel")
    parser.add_argument("--topic-id", type=int, help="Parent topic ID")
    
    args = parser.parse_args()
    
    # Load credentials
    auth_token = os.getenv("AUTH_TOKEN")
    wallet = os.getenv("WALLET_ADDRESS")
    multisig = os.getenv("MULTISIG_ADDRESS")
    private_key = os.getenv("PRIVATE_KEY")
    
    if not all([auth_token, wallet, multisig, private_key]):
        print("❌ Missing credentials in .env")
        sys.exit(1)
    
    client = OpinionTradeClient(auth_token, wallet, multisig, private_key)
    
    if args.command == "orders":
        orders = client.get_open_orders(args.topic_id)
        print(f"\n📋 Open Orders ({len(orders)}):")
        for o in orders:
            print(f"   #{o.get('orderId')} | {o.get('topicTitle')} | {o.get('side')} | {o.get('price')} | {o.get('amount')} | {o.get('transNo')}")
    
    elif args.command == "cancel":
        if not args.trans_no:
            print("❌ Need --trans-no for cancel")
            sys.exit(1)
        client.cancel_order(args.trans_no)
        print(f"✅ Order {args.trans_no} cancelled")
    
    elif args.command == "positions":
        positions = client.get_positions(args.topic_id)
        print(f"\n💰 Positions ({len(positions)}):")
        for p in positions:
            print(f"   {p.get('topicTitle')} | {p.get('sharesAmount')} shares")


if __name__ == "__main__":
    main()
