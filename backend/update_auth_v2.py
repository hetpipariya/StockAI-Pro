import sys

with open('app/routes/auth.py', 'r', encoding='utf8') as f:
    text = f.read()

# Update LoginRequest
text = text.replace(
'''class LoginRequest(BaseModel):
    """JSON login body — kept for backward compatibility with frontend."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)''',
'''class LoginRequest(BaseModel):
    """JSON login body."""
    password: str = Field(..., min_length=1)'''
)

# Update Swagger form
text = text.replace(
'''login_req = LoginRequest(username=form_data.username, password=form_data.password)''',
'''login_req = LoginRequest(password=form_data.password)'''
)

# Find the start of login definition
start_idx = text.find('@router.post("/login")\nasync def login(')
end_idx = text.find('@router.get("/login")\nasync def login_help()')

if start_idx == -1 or end_idx == -1:
    print("Could not find boundaries")
    sys.exit(1)

new_login = '''@router.post("/login")
async def login(
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
            trading_mode="PAPER"
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

text = text[:start_idx] + new_login + text[end_idx:]

with open('app/routes/auth.py', 'w', encoding='utf8') as f:
    f.write(text)

print("Updated perfectly")
