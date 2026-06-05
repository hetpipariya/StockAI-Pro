import pytest
from app.services.broker_session_manager import broker_session_manager
from app.services.db import AsyncSessionLocal, UserModel, BrokerSessionModel, init_db
from sqlalchemy import select

@pytest.mark.asyncio
async def test_broker_session_manager_flow():
    # Initialize DB tables for testing environment
    await init_db()
    
    # 1. Check initial status
    upstox_status = broker_session_manager.get_state("upstox")
    assert upstox_status["status"] in ("DISCONNECTED", "CONNECTED", "CONNECTING", "REAUTH_REQUIRED")
    
    # 2. Add a mock session and check state updates
    async with AsyncSessionLocal() as session:
        # Fetch first user
        res = await session.execute(select(UserModel.id).limit(1))
        user_id = res.scalar_one_or_none()
        
    if not user_id:
        # Create a temp test user if none exists
        async with AsyncSessionLocal() as session:
            new_user = UserModel(
                email="test_broker_session@stockai.pro",
                password_hash="testpass123",
                is_active=True
            )
            session.add(new_user)
            await session.commit()
            user_id = new_user.id
            
    # Save a session
    await broker_session_manager.save_or_update_session(
        user_id=user_id,
        broker_name="upstox",
        access_token="mock_access_token_12345",
        refresh_token="mock_refresh_token_12345"
    )
    
    # Check status is now CONNECTED
    upstox_status = broker_session_manager.get_state("upstox")
    assert upstox_status["status"] == "CONNECTED"
    assert upstox_status["token_valid"] is True
    
    # 3. Disconnect and check status is DISCONNECTED
    await broker_session_manager.disconnect_broker(
        user_id=user_id,
        broker_name="upstox"
    )
    
    upstox_status = broker_session_manager.get_state("upstox")
    assert upstox_status["status"] == "DISCONNECTED"
    assert upstox_status["token_valid"] is False
