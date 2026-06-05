from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from abc import ABC, abstractmethod

from sqlalchemy import select
from app.services.db import AsyncSessionLocal, UserModel, BrokerSessionModel
from app.connectors import get_market_data_connector

logger = logging.getLogger(__name__)

class BrokerSession(ABC):
    @abstractmethod
    def get_broker_name(self) -> str:
        pass

    @abstractmethod
    async def validate_token(self, access_token: str) -> bool:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

class BrokerSessionManager:
    """Central manager for broker sessions, status monitoring, and WS stream hooks."""
    
    def __init__(self):
        self._states: Dict[str, Dict[str, Any]] = {
            "upstox": {
                "status": "DISCONNECTED",
                "token_valid": False,
                "websocket_connected": False,
                "last_auth_success": None,
                "last_auth_failure": None,
                "reconnect_attempts": 0,
                "access_token": None,
                "refresh_token": None
            },
            "smartapi": {
                "status": "DISCONNECTED",
                "token_valid": False,
                "websocket_connected": False,
                "last_auth_success": None,
                "last_auth_failure": None,
                "reconnect_attempts": 0,
                "access_token": None,
                "refresh_token": None
            }
        }

    def get_state(self, broker: str) -> Dict[str, Any]:
        return self._states.get(broker.lower(), {
            "broker": broker,
            "status": "DISCONNECTED",
            "token_valid": False,
            "websocket_connected": False,
            "last_auth_success": None,
            "last_auth_failure": None,
            "reconnect_attempts": 0,
            "access_token": None,
            "refresh_token": None
        })

    def update_state(self, broker: str, **kwargs) -> None:
        b = broker.lower()
        if b in self._states:
            old_status = self._states[b].get("status")
            self._states[b].update(kwargs)
            new_status = self._states[b].get("status")
            if old_status != new_status:
                self.log_event("[BROKER_STATE]", b, details=f"status_changed: {old_status} -> {new_status}")

    def log_event(self, event_tag: str, broker: str, user_id: str = "1", details: str = ""):
        state = self.get_state(broker)
        status = state.get("status", "DISCONNECTED")
        
        token_age = "N/A"
        last_success = state.get("last_auth_success")
        if last_success:
            try:
                dt = datetime.fromisoformat(last_success)
                age = (datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds()
                token_age = f"{age:.1f}s"
            except Exception:
                pass
                
        expiry_time = "N/A"
        
        logger.info(
            f"{event_tag} broker={broker} user={user_id} state={status} token_age={token_age} expiry_time={expiry_time} {details}".strip()
        )

    def get_active_token_sync(self, broker_name: str) -> Optional[str]:
        """Load and return the dynamic token from the database synchronously."""
        b = broker_name.lower()
        state = self.get_state(b)
        if state.get("access_token"):
            return state["access_token"]

        try:
            from app.services.db import get_sync_db_session, BrokerSessionModel, UserModel
            db_gen = get_sync_db_session()
            session = next(db_gen)
            if session is None:
                return None
            try:
                user_id = session.query(UserModel.id).limit(1).scalar()
                if not user_id:
                    return None
                
                bs = session.query(BrokerSessionModel).filter(
                    BrokerSessionModel.user_id == user_id,
                    BrokerSessionModel.broker_name == b
                ).first()
                if bs and bs.access_token:
                    self.update_state(
                        b,
                        access_token=bs.access_token,
                        refresh_token=bs.refresh_token,
                        status=bs.status,
                        token_valid=(bs.status == "CONNECTED")
                    )
                    self.log_event("[TOKEN_LOADED]", b, user_id=str(user_id), details="Loaded token from DB synchronously")
                    return bs.access_token
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"Failed to query active token synchronously for {b}: {e}")
        return None

    async def mark_token_expired_db(self, broker_name: str) -> None:
        """Mark broker status as TOKEN_EXPIRED in database."""
        b = broker_name.lower()
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserModel.id).limit(1))
            user_id = res.scalar_one_or_none()
            if not user_id:
                return
            
            broker_res = await session.execute(
                select(BrokerSessionModel).where(
                    BrokerSessionModel.user_id == user_id,
                    BrokerSessionModel.broker_name == b
                )
            )
            bs = broker_res.scalars().first()
            if bs:
                bs.status = "TOKEN_EXPIRED"
                bs.last_auth_failure = datetime.utcnow()
                await session.commit()
            
            self.update_state(
                b,
                status="TOKEN_EXPIRED",
                token_valid=False,
                last_auth_failure=datetime.utcnow().isoformat()
            )
            self.log_event("[TOKEN_EXPIRED]", b, user_id=str(user_id), details="Token marked as EXPIRED in DB")

    async def load_sessions_on_startup(self) -> None:
        """Startup routine: Load and validate saved token from DB, then start WebSocket."""
        logger.info("[STARTUP] Broker Session Manager: Initializing saved sessions...")
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserModel.id).limit(1))
            user_id = res.scalar_one_or_none()
            if not user_id:
                logger.warning("[STARTUP] No user found in database. Skipping broker session startup.")
                return

            broker_res = await session.execute(
                select(BrokerSessionModel).where(BrokerSessionModel.user_id == user_id)
            )
            broker_sessions = broker_res.scalars().all()
            
            for bs in broker_sessions:
                broker_name = bs.broker_name.lower()
                if not bs.access_token:
                    logger.info(f"[STARTUP] Broker session {broker_name} has no token. Skipping.")
                    continue
                
                logger.info(f"[STARTUP] Validating saved token for broker: {broker_name}")
                self.update_state(broker_name, status="CONNECTING", access_token=bs.access_token, refresh_token=bs.refresh_token)
                
                is_valid = await self.validate_token_online(broker_name, bs.access_token)
                if is_valid:
                    logger.info(f"[BROKER_CONNECTED] Stored token for {broker_name} is valid.")
                    self.update_state(
                        broker_name,
                        status="CONNECTED",
                        token_valid=True,
                        last_auth_success=datetime.utcnow().isoformat(),
                        access_token=bs.access_token,
                        refresh_token=bs.refresh_token
                    )
                    bs.status = "CONNECTED"
                    bs.last_auth_success = datetime.utcnow()
                    await session.commit()
                    
                    self.log_event("[TOKEN_LOADED]", broker_name, user_id=str(user_id), details="Loaded valid startup session")
                    
                    try:
                        router = get_market_data_connector()
                        router._active_broker = broker_name
                        upstox = router._create_upstox_connector(force_new=True)
                        upstox.access_token = bs.access_token
                        upstox.refresh_token = bs.refresh_token
                        upstox._session.headers["Authorization"] = f"Bearer {bs.access_token}"
                        upstox._is_logged_in = True
                        
                        logger.info(f"[BROKER_WS_CONNECTED] Starting WS client for {broker_name}")
                        from app.websocket.handler import auto_start_ws
                        await auto_start_ws()
                        self.update_state(broker_name, websocket_connected=True)
                    except Exception as e:
                        logger.error(f"[BROKER_WS_DISCONNECTED] Failed to startup WS for {broker_name}: {e}")
                        self.update_state(broker_name, status="WEBSOCKET_FAILED", websocket_connected=False)
                else:
                    logger.warning(f"[BROKER_TOKEN_EXPIRED] Stored token for {broker_name} has expired.")
                    self.update_state(
                        broker_name,
                        status="TOKEN_EXPIRED",
                        token_valid=False,
                        last_auth_failure=datetime.utcnow().isoformat(),
                        access_token=None,
                        refresh_token=None
                    )
                    bs.status = "TOKEN_EXPIRED"
                    bs.last_auth_failure = datetime.utcnow()
                    await session.commit()
                    self.log_event("[TOKEN_EXPIRED]", broker_name, user_id=str(user_id), details="Stored token expired on startup validation")

    async def validate_token_online(self, broker: str, access_token: str) -> bool:
        """Call broker APIs to verify that the access token is fully valid."""
        if broker.lower() == "upstox":
            try:
                import requests
                headers = {
                    "Accept": "application/json",
                    "Api-Version": "2.0",
                    "Authorization": f"Bearer {access_token}"
                }
                res = requests.get("https://api.upstox.com/v2/user/profile", headers=headers, timeout=5)
                return res.status_code == 200
            except Exception as e:
                logger.warning(f"Upstox token validation failed: {e}")
                return False
        elif broker.lower() == "smartapi":
            return True
        return False

    async def save_or_update_session(
        self, user_id: int, broker_name: str, access_token: str, refresh_token: Optional[str] = None
    ) -> None:
        """Saves a newly exchanged access token into the DB and marks status CONNECTED."""
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(BrokerSessionModel).where(
                    BrokerSessionModel.user_id == user_id,
                    BrokerSessionModel.broker_name == broker_name
                )
            )
            bs = res.scalars().first()
            if not bs:
                bs = BrokerSessionModel(
                    user_id=user_id,
                    broker_name=broker_name,
                    status="CONNECTED",
                    access_token=access_token,
                    refresh_token=refresh_token,
                    last_auth_success=datetime.utcnow()
                )
                session.add(bs)
            else:
                bs.access_token = access_token
                bs.refresh_token = refresh_token or bs.refresh_token
                bs.status = "CONNECTED"
                bs.last_auth_success = datetime.utcnow()
            
            await session.commit()
            
            logger.info(f"[BROKER_CONNECTED] Token saved/updated for broker {broker_name}.")
            self.update_state(
                broker_name,
                status="CONNECTED",
                token_valid=True,
                last_auth_success=datetime.utcnow().isoformat(),
                websocket_connected=True,
                access_token=access_token,
                refresh_token=refresh_token
            )
            self.log_event("[TOKEN_LOADED]", broker_name, user_id=str(user_id), details="OAuth token exchanged and saved")

    async def disconnect_broker(self, user_id: int, broker_name: str) -> None:
        """Clears broker session, closes websocket connections and sets state to DISCONNECTED."""
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(BrokerSessionModel).where(
                    BrokerSessionModel.user_id == user_id,
                    BrokerSessionModel.broker_name == broker_name
                )
            )
            bs = res.scalars().first()
            if bs:
                bs.access_token = None
                bs.refresh_token = None
                bs.status = "DISCONNECTED"
                bs.last_auth_failure = None
                await session.commit()
            
            try:
                router = get_market_data_connector()
                if broker_name.lower() == "upstox":
                    if hasattr(router, "_upstox_connector") and router._upstox_connector:
                        upstox = router._upstox_connector
                        upstox._ws_should_reconnect = False
                        if upstox._ws:
                            upstox._ws.close()
                        upstox.access_token = ""
                        upstox._is_logged_in = False
                logger.info(f"[BROKER_WS_DISCONNECTED] Closed WS connection for broker: {broker_name}")
            except Exception as e:
                logger.warning(f"Error stopping websocket: {e}")
                
            self.update_state(
                broker_name,
                status="DISCONNECTED",
                token_valid=False,
                websocket_connected=False,
                access_token=None,
                refresh_token=None
            )
            self.log_event("[WS_STOP]", broker_name, user_id=str(user_id), details="Manual disconnect requested")

# Global singleton manager instance
broker_session_manager = BrokerSessionManager()
