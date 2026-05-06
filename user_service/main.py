from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os
import re
from datetime import datetime
import requests
from dotenv import load_dotenv
load_dotenv() 

app = FastAPI(title="User Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Upstash REST API configuration
UPSTASH_URL = os.getenv("UPSTASH_URL")
UPSTASH_TOKEN = os.getenv("UPSTASH_TOKEN")
if not UPSTASH_URL or not UPSTASH_TOKEN:
    raise ValueError("Missing Upstash configuration")

def upstash_command(command, *args):
    """Execute Redis command via Upstash REST API and return result"""
    # Build URL with command and arguments
    args_str = '/'.join(str(a).replace(' ', '%20') for a in args)
    url = f"{UPSTASH_URL}/{command}/{args_str}"
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        result = response.json()
        # Upstash returns [result] or {"result": value} format
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        if isinstance(result, dict) and "result" in result:
            return result["result"]
        return result
    except Exception as e:
        print(f"Upstash error for {command}: {e}")
        return None

def upstash_set(key, value):
    """Set a key-value pair"""
    return upstash_command("SET", key, value)

def upstash_get(key):
    """Get a value by key"""
    return upstash_command("GET", key)

def upstash_incr(key):
    """Increment a key and return new value"""
    result = upstash_command("INCR", key)
    try:
        return int(result) if result else 1
    except:
        return 1

def upstash_keys(pattern):
    """Get all keys matching pattern"""
    result = upstash_command("KEYS", pattern)
    if isinstance(result, list):
        return result
    return []

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    address: str = ""
    phone: str = ""

class UserLogin(BaseModel):
    email: str
    password: str

class UserUpdate(BaseModel):
    address: str = None
    phone: str = None

def validate_phone(phone: str) -> bool:
    if not phone:
        return True
    clean_phone = re.sub(r'\D', '', phone)
    return 10 <= len(clean_phone) <= 15

def validate_email(email: str) -> bool:
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_regex, email) is not None

def get_all_users():
    """Get all users from Upstash"""
    users = []
    keys = upstash_keys("user:*")
    for key in keys:
        value = upstash_get(key)
        if value and isinstance(value, str):
            try:
                users.append(json.loads(value))
            except:
                pass
    return users

@app.get("/health")
def health():
    return {"service": "User Service", "status": "running"}

@app.post("/register")
def register(user: UserCreate):
    if not validate_email(user.email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    if user.phone and not validate_phone(user.phone):
        raise HTTPException(status_code=400, detail="Invalid phone number (must be 10-15 digits)")

    # Check if email already exists
    existing_users = get_all_users()
    for u in existing_users:
        if u["email"].lower() == user.email.lower():
            raise HTTPException(status_code=400, detail="Email already registered")

    # Get next user ID
    user_id = upstash_incr("users:next_id")
    
    record = {
        "id": user_id,
        "username": user.username,
        "email": user.email,
        "password": user.password,
        "address": user.address.strip() if user.address else "",
        "phone": user.phone.strip() if user.phone else "",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    
    upstash_set(f"user:{user_id}", json.dumps(record))

    safe_user = dict(record)
    safe_user.pop("password", None)
    return {"message": "User registered successfully", "user": safe_user}

@app.post("/login")
def login(credentials: UserLogin):
    users = get_all_users()
    for user in users:
        if user["email"].lower() == credentials.email.lower() and user["password"] == credentials.password:
            safe_user = dict(user)
            safe_user.pop("password", None)
            return {"message": "Login successful", "user": safe_user}
    raise HTTPException(status_code=401, detail="Invalid email or password")

@app.get("/users")
def get_users():
    users = get_all_users()
    for user in users:
        user.pop("password", None)
    users.sort(key=lambda x: x["id"])
    return users

@app.get("/users/{user_id}")
def get_user(user_id: int):
    value = upstash_get(f"user:{user_id}")
    if not value:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        user = json.loads(value)
        user.pop("password", None)
        return user
    except:
        raise HTTPException(status_code=404, detail="User not found")

@app.put("/users/{user_id}")
def update_user(user_id: int, update: UserUpdate):
    value = upstash_get(f"user:{user_id}")
    if not value:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        user = json.loads(value)
    except:
        raise HTTPException(status_code=404, detail="User not found")

    if update.address is not None:
        user["address"] = update.address.strip()
    if update.phone is not None:
        if not validate_phone(update.phone):
            raise HTTPException(status_code=400, detail="Invalid phone number")
        user["phone"] = update.phone.strip()

    user["updated_at"] = datetime.utcnow().isoformat()
    upstash_set(f"user:{user_id}", json.dumps(user))

    safe_user = dict(user)
    safe_user.pop("password", None)
    return {"message": "User updated successfully", "user": safe_user}

@app.patch("/users/{user_id}/address")
def update_address(user_id: int, address: str):
    value = upstash_get(f"user:{user_id}")
    if not value:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        user = json.loads(value)
    except:
        raise HTTPException(status_code=404, detail="User not found")
    user["address"] = address.strip()
    user["updated_at"] = datetime.utcnow().isoformat()
    upstash_set(f"user:{user_id}", json.dumps(user))
    return {"message": "Address updated successfully"}

@app.patch("/users/{user_id}/phone")
def update_phone(user_id: int, phone: str):
    if not validate_phone(phone):
        raise HTTPException(status_code=400, detail="Invalid phone number")
    value = upstash_get(f"user:{user_id}")
    if not value:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        user = json.loads(value)
    except:
        raise HTTPException(status_code=404, detail="User not found")
    user["phone"] = phone.strip()
    user["updated_at"] = datetime.utcnow().isoformat()
    upstash_set(f"user:{user_id}", json.dumps(user))
    return {"message": "Phone number updated successfully"}
# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# import redis
# import json
# import os
# import re
# from datetime import datetime

# app = FastAPI(title="User Service")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
# REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)

# class UserCreate(BaseModel):
#     username: str
#     email: str
#     password: str
#     address: str = ""
#     phone: str = ""

# class UserLogin(BaseModel):
#     email: str
#     password: str

# class UserUpdate(BaseModel):
#     address: str = None
#     phone: str = None

# def validate_phone(phone: str) -> bool:
#     if not phone:
#         return True
#     clean_phone = re.sub(r'\D', '', phone)
#     return 10 <= len(clean_phone) <= 15

# def validate_email(email: str) -> bool:
#     email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
#     return re.match(email_regex, email) is not None

# @app.get("/health")
# def health():
#     return {"service": "User Service", "status": "running"}

# @app.post("/register")
# def register(user: UserCreate):
#     if not validate_email(user.email):
#         raise HTTPException(status_code=400, detail="Invalid email format")
#     if user.phone and not validate_phone(user.phone):
#         raise HTTPException(status_code=400, detail="Invalid phone number (must be 10-15 digits)")

#     # Check if email already exists
#     for key in r.scan_iter("user:*"):
#         value = r.get(key)
#         if value:
#             existing = json.loads(value)
#             if existing["email"].lower() == user.email.lower():
#                 raise HTTPException(status_code=400, detail="Email already registered")

#     user_id = r.incr("users:next_id")
#     record = {
#         "id": user_id,
#         "username": user.username,
#         "email": user.email,
#         "password": user.password,   # store plain text (or hash in production)
#         "address": user.address.strip() if user.address else "",
#         "phone": user.phone.strip() if user.phone else "",
#         "created_at": datetime.utcnow().isoformat(),
#         "updated_at": datetime.utcnow().isoformat()
#     }
#     r.set(f"user:{user_id}", json.dumps(record))

#     safe_user = dict(record)
#     safe_user.pop("password", None)
#     return {"message": "User registered successfully", "user": safe_user}

# @app.post("/login")
# def login(credentials: UserLogin):
#     # Iterate over all users directly (without stripping passwords)
#     for key in r.scan_iter("user:*"):
#         value = r.get(key)
#         if value:
#             user = json.loads(value)
#             if user["email"].lower() == credentials.email.lower() and user["password"] == credentials.password:
#                 safe_user = dict(user)
#                 safe_user.pop("password", None)
#                 return {"message": "Login successful", "user": safe_user}
#     raise HTTPException(status_code=401, detail="Invalid email or password")

# @app.get("/users")
# def get_users():
#     users = []
#     for key in r.scan_iter("user:*"):
#         value = r.get(key)
#         if value:
#             user = json.loads(value)
#             user.pop("password", None)
#             users.append(user)
#     users.sort(key=lambda x: x["id"])
#     return users

# @app.get("/users/{user_id}")
# def get_user(user_id: int):
#     value = r.get(f"user:{user_id}")
#     if not value:
#         raise HTTPException(status_code=404, detail="User not found")
#     user = json.loads(value)
#     user.pop("password", None)
#     return user

# @app.put("/users/{user_id}")
# def update_user(user_id: int, update: UserUpdate):
#     value = r.get(f"user:{user_id}")
#     if not value:
#         raise HTTPException(status_code=404, detail="User not found")
#     user = json.loads(value)

#     if update.address is not None:
#         user["address"] = update.address.strip()
#     if update.phone is not None:
#         if not validate_phone(update.phone):
#             raise HTTPException(status_code=400, detail="Invalid phone number")
#         user["phone"] = update.phone.strip()

#     user["updated_at"] = datetime.utcnow().isoformat()
#     r.set(f"user:{user_id}", json.dumps(user))

#     safe_user = dict(user)
#     safe_user.pop("password", None)
#     return {"message": "User updated successfully", "user": safe_user}

# @app.patch("/users/{user_id}/address")
# def update_address(user_id: int, address: str):
#     value = r.get(f"user:{user_id}")
#     if not value:
#         raise HTTPException(status_code=404, detail="User not found")
#     user = json.loads(value)
#     user["address"] = address.strip()
#     user["updated_at"] = datetime.utcnow().isoformat()
#     r.set(f"user:{user_id}", json.dumps(user))
#     return {"message": "Address updated successfully"}

# @app.patch("/users/{user_id}/phone")
# def update_phone(user_id: int, phone: str):
#     if not validate_phone(phone):
#         raise HTTPException(status_code=400, detail="Invalid phone number")
#     value = r.get(f"user:{user_id}")
#     if not value:
#         raise HTTPException(status_code=404, detail="User not found")
#     user = json.loads(value)
#     user["phone"] = phone.strip()
#     user["updated_at"] = datetime.utcnow().isoformat()
#     r.set(f"user:{user_id}", json.dumps(user))
#     return {"message": "Phone number updated successfully"}