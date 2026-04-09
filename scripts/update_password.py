#!/usr/bin/env python3
"""
Update admin user password for StockAI Pro
Usage: python scripts/update_password.py [username] [new_password]
"""

import sys
import asyncio
import logging
from pathlib import Path
import os

# Add parent directory to path
script_dir = Path(__file__).parent
repo_root = script_dir.parent
backend_dir = repo_root / "backend"

# Try multiple import paths
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(repo_root))

# Change to backend directory for app imports
if os.path.exists(backend_dir / "app"):
    os.chdir(backend_dir)

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

try:
    from app.config import DATABASE_URL
    from app.services.db import Base, UserModel
    from app.utils.auth_utils import hash_password
except ImportError:
    # Fallback for running from backend directory
    from app.config import DATABASE_URL
    from app.services.db import Base, UserModel
    from app.utils.auth_utils import hash_password

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def update_password(username: str, new_password: str) -> bool:
    """Update user password in database"""
    try:
        # Create async engine and session
        engine = create_async_engine(DATABASE_URL, echo=False)
        AsyncSessionLocal = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        async with AsyncSessionLocal() as session:
            # Find user
            result = await session.execute(
                select(UserModel).where(UserModel.username == username)
            )
            user = result.scalars().first()
            
            if not user:
                logger.error(f"❌ User '{username}' not found")
                await engine.dispose()
                return False
            
            # Hash new password
            hashed_password = hash_password(new_password)
            
            # Update password
            user.password_hash = hashed_password
            session.add(user)
            await session.commit()
            
            logger.info(f"✅ Password updated for user '{username}'")
            await engine.dispose()
            return True
            
    except Exception as e:
        logger.error(f"❌ Error updating password: {e}")
        return False


async def create_admin_user(username: str, password: str, email: str = None) -> bool:
    """Create new admin user if doesn't exist"""
    try:
        # Normalize username to lowercase
        username = username.lower().strip()
        
        # Create async engine and session
        engine = create_async_engine(DATABASE_URL, echo=False)
        AsyncSessionLocal = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        async with AsyncSessionLocal() as session:
            # Check if user exists
            result = await session.execute(
                select(UserModel).where(UserModel.username == username)
            )
            existing_user = result.scalars().first()
            
            if existing_user:
                logger.warning(f"⚠️  User '{username}' already exists")
                await engine.dispose()
                return False
            
            # Create new user
            hashed_password = hash_password(password)
            new_user = UserModel(
                username=username,
                email=email.lower() if email else None,
                password_hash=hashed_password,
                is_active=True,
                is_verified=True,
                starting_capital=100000.0,
                trading_mode="PAPER"
            )
            
            session.add(new_user)
            await session.commit()
            
            logger.info(f"✅ Admin user '{username}' created successfully")
            await engine.dispose()
            return True
            
    except Exception as e:
        logger.error(f"❌ Error creating user: {e}")
        return False


async def delete_all_users() -> bool:
    """Delete all users from database"""
    try:
        # Create async engine and session
        engine = create_async_engine(DATABASE_URL, echo=False)
        AsyncSessionLocal = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        async with AsyncSessionLocal() as session:
            # Get count before delete
            result = await session.execute(select(UserModel))
            users = result.scalars().all()
            count = len(users)
            
            if count == 0:
                logger.info("ℹ️  No users to delete")
                await engine.dispose()
                return True
            
            # Delete all users
            stmt = delete(UserModel)
            await session.execute(stmt)
            await session.commit()
            
            logger.info(f"🗑️  Deleted {count} user(s)")
            await engine.dispose()
            return True
            
    except Exception as e:
        logger.error(f"❌ Error deleting users: {e}")
        return False


async def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/update_password.py <username> <new_password>")
        print("  python scripts/update_password.py --create <username> <password> [email]")
        print("  python scripts/update_password.py --delete-all-and-create <username> <password> [email]")
        print("\nExample:")
        print("  python scripts/update_password.py admin Pipariya073")
        print("  python scripts/update_password.py --delete-all-and-create Pipariya PHet@07310")
        sys.exit(1)
    
    if sys.argv[1] == "--create":
        if len(sys.argv) < 4:
            print("Usage: python scripts/update_password.py --create <username> <password> [email]")
            sys.exit(1)
        username = sys.argv[2]
        password = sys.argv[3]
        email = sys.argv[4] if len(sys.argv) > 4 else None
        success = await create_admin_user(username, password, email)
    elif sys.argv[1] == "--delete-all-and-create":
        if len(sys.argv) < 4:
            print("Usage: python scripts/update_password.py --delete-all-and-create <username> <password> [email]")
            sys.exit(1)
        username = sys.argv[2]
        password = sys.argv[3]
        email = sys.argv[4] if len(sys.argv) > 4 else None
        # First delete all users
        await delete_all_users()
        # Then create new user
        success = await create_admin_user(username, password, email)
    else:
        username = sys.argv[1]
        password = sys.argv[2]
        success = await update_password(username, password)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
