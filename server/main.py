from datetime import datetime, timedelta, timezone
import os
import uuid

import uvicorn

from fastapi import FastAPI, HTTPException, Depends, Response, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from email_validator import validate_email, EmailNotValidError
from decouple import config
from jose import jwt, JWTError
from password_strength import PasswordPolicy
from passlib.context import CryptContext
from pymongo import MongoClient

app = FastAPI()
#TODO: replace with bcrypt to avoid logging error
encrypter = CryptContext(schemes=["bcrypt"], deprecated="auto")

client = MongoClient(config("MONGODB_KEY"))

# Check if cluster is connected
try:
    client.admin.command('ping')
    print("MongoDB connection: Successful")
except Exception as e:
    print(f"MongoDB connection: Failed - {e}")

db = client["main"]
users = db["users"]
posts = db["posts"]
users.delete_many({})

users.insert_one({"username": "admin", 
                  "email": "",
                  "password": encrypter.hash("admin"),
                  "elevation": "admin"})

pwd_policy = PasswordPolicy.from_names(
    length=8,
    uppercase=1,
    numbers=1,
    special=1
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # update once domain is known
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str
    
class AuthToken(BaseModel):
    message: str
    access_token: str
    token_type: str
    
def generate_token(username: str, elevation: str, expiry: int) -> str:
    encode = {"user": username,
              "elevation": elevation, 
              "exp": datetime.now(timezone.utc) + timedelta(minutes=int(expiry))}
    return jwt.encode(encode, config("SECRET_KEY"), algorithm=config("AUTH_ALGORITHM"))

def verify_token(token: str):
    try:
        payload = jwt.decode(token, config("SECRET_KEY"), algorithms=[config("AUTH_ALGORITHM")])
        username = payload.get("user")
        if username is None:
            raise HTTPException(status_code=403, detail="Invalid token")
        return payload
    except JWTError:
        raise HTTPException(status_code=403, detail="Invalid token")
    
@app.get("/")
async def read_root():
    return {"message": "Welcome to the FastAPI application"}

def validate_request(request: RegisterRequest) -> None:
    """Checks password, email and username to ensure all are valid and do not already exist in the collection

    Args:
        request (RegisterRequest): request object containing username, email and password
    """
    
    _validate_password(request.password)
    _validate_username(request.username)
    _validate_email(request.email)

def _validate_password(password: str) -> None:
    
    """Validates a provided password against common password policies. Raises an exception if the password is invalid.
    """
    
    error_msg = []
    validation = pwd_policy.test(password)
    
    error_map = {
        "Length(8)": "Password must be at least 8 characters long",
        "Uppercase(1)": "Password must contain at least one uppercase letter",
        "Numbers(1)": "Password must contain at least one number",
        "Special(1)": "Password must contain at least one special character"
    }
    
    for policy in validation:
        error_msg.append(error_map.get(str(policy), "Unknown policy violation"))
        
    if len(error_msg) > 0:
        error_msg = ", ".join(error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    
def _validate_username(username: str) -> None:
    
    """Ensures a provided username does not already exist in the collection
    """
    
    user = users.find_one({"username": username})
    
    if user:
        raise HTTPException(status_code=400, detail="Username already registered, please login")

def _validate_email(email: str) -> None:
    
    """Ensures a provided email does not already exist in the collection and is valid
    """

    # Check whether provided email is a valid address    
    try:
        validate_email(email)
    except EmailNotValidError as e:
        raise HTTPException(status_code=400, detail=f"Invalid email: {e}")
    
    # Ensure email does not already exist in the collection
    email = users.find_one({"email": email})
    
    if email:
        raise HTTPException(status_code=400, detail="Email already registered, please login")

def encrypt_password(password: str) -> str:
    
    """Encrypts a provided password
    """
    
    return encrypter.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    
    """Verifies a provided password against the hashed password stored in the database
    """
    
    return encrypter.verify(plain_password, hashed_password)
    
@app.post("/register")
async def register(request: RegisterRequest) -> dict:
    
    # validate incoming request
    validate_request(request)

    users.insert_one({
        "username": request.username,
        "email": request.email,
        "password": encrypt_password(request.password),
        "elevation": "user"
    })
    
    # Check if user was successfully registered
    new_user = users.find_one({"username": request.username})
    if new_user:
        return {"message": "User registered successfully"}
    else:
        raise HTTPException(status_code=500, detail="User registration failed")
    
@app.post("/login", response_model = AuthToken)
async def login(response: Response, request: OAuth2PasswordRequestForm = Depends()) -> AuthToken:
    user = users.find_one({"username": request.username})
    
    print(user)
    
    if not user:
        # try email address as well
        user = users.find_one({"email": request.username})
        
        if not user:
            raise HTTPException(status_code=400, detail="Invalid username or email")
     
    print(user)
        
    if not verify_password(request.password, user["password"]):
        raise HTTPException(status_code=400, detail="Invalid password")
    
    auth_token = generate_token(user["username"], user["elevation"], config("TOKEN_EXPIRY"))
    response.set_cookie(key = "auth_token", value = auth_token, httponly = True, secure = True, samesite = "Strict")
    return {"message": "Succesfully logged in!", "access_token": auth_token, "token_type": "bearer"}

@app.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie("auth_token")
    return {"message": "Logged out successfully"}

@app.get("/verify")
async def verify_user(request: Request) -> dict:
    token = request.cookies.get("auth_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(token)
    username = payload.get("user")
    elevation = payload.get("elevation")
    return {"message": "Token verified", 
            "username": username,
            "elevation": elevation}
    
@app.post("/create")
async def create_post(title: str = Form(...),
                      content: str = Form(...),
                      cover_image: UploadFile = File(...)) -> dict:
    
    upload_dir = "uploads"
    # create unique post id to store image(s)
    post_id = str(uuid.uuid4())
    cover_id = f"{post_id}_cover"
    upload_path = os.path.join(upload_dir, cover_id)
    os.makedirs(upload_dir, exist_ok=True)
    with open(upload_path, "wb") as buffer:
        buffer.write(await cover_image.read())
    
    posts.insert_one({
        "title": title,
        "body": content,
        "cover_image": cover_id
    })
    
    return {"message": "Post created successfully"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)