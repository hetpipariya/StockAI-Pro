import re
with open('app/routes/auth.py', 'r', encoding='utf8') as f:
    text = f.read()

# Remove username from LoginRequest
text = re.sub(
    r'class LoginRequest\(BaseModel\):.*?password: str = Field\(..., min_length=1\)',
    'class LoginRequest(BaseModel):\n    password: str = Field(..., min_length=1)',
    text, flags=re.DOTALL
)

# Update the login function body to only check master password and return terminal_user
login_body = '''
# ── GET /api/auth/me ───────────────────────────────────────────────
'''
new_login_func = '''async def login(
    data: LoginRequest,
    session: AsyncSession = Depends(get_async_session),
):
    master_hash = "/AD/c1Gl0Shiloe1zzmwPaqNKJ/2" 
    
    if not verify_password(data.password.strip(), master_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth Denied. Invalid Master Password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    result = await session.execute(select(UserModel).limit(1))
    user = result.scalars().first()
    
    if not user:
        user = UserModel(
            username="terminal_master",
            email="terminal@stockai.pro",
            password_hash=master_hash,
            is_active=True,
            is_verified=True,
            trading_mode="PAPER",
            created_at=datetime.utcnow(),
            last_login=datetime.utcnow()
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(user.id)

    user.refresh_token_hash = hash_refresh_token(refresh_token)
    user.last_login = datetime.utcnow()
    await session.commit()

    return {
        "status": "ok",
        "message": "Login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }
'''

text = re.sub(
    r'async def login\(.*?(?=\n\n\s*@compat_router\.post)',
    new_login_func,
    text, flags=re.DOTALL
)

# Fix Swagger form data to use dummy user
text = re.sub(
    r'login_req = LoginRequest\(username=form_data\.username, password=form_data\.password\)',
    'login_req = LoginRequest(password=form_data.password)',
    text
)

# Disable Signup
text = re.sub(
    r'async def signup\(.*?return \{\s*"status": "ok".*?\}',
    'async def signup(\n    data: SignupRequest,\n    session: AsyncSession = Depends(get_async_session),\n):\n    raise HTTPException(status_code=403, detail="Signup disabled. Terminal Access Only.")\n    return {}',
    text, flags=re.DOTALL
)

with open('app/routes/auth.py', 'w', encoding='utf8') as f:
    f.write(text)

print("Updated auth.py")
