from datetime import datetime, timedelta, timezone
import os
import uuid

from io import BytesIO

import uvicorn

from fastapi import FastAPI, HTTPException, Depends, Response, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from email_validator import validate_email, EmailNotValidError
from decouple import config
from jose import jwt, JWTError
from markdown import markdown
from password_strength import PasswordPolicy
from passlib.context import CryptContext
from PIL import Image
from pymongo import MongoClient

from summarizer import read_pdf, summarize_content, suggest_title

app = FastAPI()
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
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
profiles = db["profiles"]
users.delete_many({})
#posts.delete_many({})

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
    allow_origins=["http://localhost:3000"],
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
    
class ProfileAddRequest(BaseModel):
    prompt: str
    
class ProfileGetRequest(BaseModel):
    profile_id: str
    
def generate_token(username: str, elevation: str, expiry: int) -> str:
    encode = {"user": username,
              "elevation": elevation, 
              "exp": datetime.now(timezone.utc) + timedelta(minutes=expiry)}
    return jwt.encode(encode, config("SECRET_KEY"), algorithm=config("AUTH_ALGORITHM"))

def verify_token(token: str):
    try:
        payload = jwt.decode(token, config("SECRET_KEY"), algorithms=[config("AUTH_ALGORITHM")])
        username = payload.get("user")
        exp = payload.get("exp")
        current_time = datetime.now(timezone.utc).timestamp()
        
        print(f"Token expiration time: {exp}")
        print(f"Current time: {current_time}")
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
    
    print(config("TOKEN_EXPIRY"))
    
    auth_token = generate_token(user["username"], user["elevation"], int(config("TOKEN_EXPIRY")))
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
                      cover_image: UploadFile = File(None),
                      cover_image_url: str = Form(None),
                      post_id: str = Form(None)) -> dict:
    
    upload_dir = "uploads"
    
    print(post_id)
    
    if not post_id:
        post_id = str(uuid.uuid4())
        
    os.makedirs(os.path.join(upload_dir, post_id), exist_ok=True)

    # ensure file can be coerced to .webp before uploading to db
    
    if cover_image: # if a custom image is provided, upload to server for conversion
        cover_id = f"{post_id}_cover.webp"
        upload_path = os.path.join(os.path.join(upload_dir, post_id), cover_id)
        
        try:
            img = Image.open(BytesIO(await cover_image.read()))
            conv_img = img.convert("RGB")
            conv_img.save(upload_path, "webp")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error converting image: {e}")
    else:
        cover_id = cover_image_url
    
    created_at = datetime.now(timezone.utc)
    
    posts.insert_one({
        "post_id": post_id,
        "title": title,
        "content": content,
        "cover_image": cover_id,
        "created_at": created_at,
        "modified_at": created_at
    })
        
    return {"message": "Post created successfully"}

@app.get("/profiles")
async def get_profiles() -> dict:
    prompt_profiles = list(profiles.find({}, {"_id": 0}))
    return {"message": "Prompt profiles loaded successfully", "profiles": prompt_profiles}

@app.post("/add_profile")
async def add_profile(request: ProfileAddRequest) -> dict:
    created_at = datetime.now(timezone.utc)
    profiles.insert_one({
            "name": f"prompt_{created_at.strftime('%Y%m%d%H%M%S')}",
            "prompt": request.prompt,
            "created_at": created_at
        })
    return {"message": "Prompt Profile added successfully"}

@app.post("/get_profile")
async def get_profile(request: ProfileGetRequest) -> dict:
    profile = profiles.find_one({"name": request.profile_id}, {"_id": 0})
    if not profile:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"message": "Prompt profile loaded successfully", "profile": profile}

@app.post("/autofill")
async def autofill_data(pdf: UploadFile = File(...),
                        user_prompt: str = Form(...)) -> dict:
    
    upload_dir = config("UPLOAD_DIR")
    def_image = config("DEF_IMAGE")
    
    cover_image_url = f"{upload_dir}/{def_image}"
    
    post_id = str(uuid.uuid4())
    os.makedirs(os.path.join(upload_dir, post_id), exist_ok=True)
    pdf_path = os.path.join(os.path.join(upload_dir, post_id), f"{post_id}.pdf")
    with open(pdf_path, "wb") as pdf_file:
        pdf_file.write(await pdf.read())
        
    parsed_content = read_pdf(pdf_path)
    summarized_content = markdown(summarize_content(parsed_content, user_prompt))
    suggested_title = suggest_title(parsed_content)
    #suggested_sector = suggested_sector(parsed_content)
    #suggested_img_kwords = suggested_img_kwords(parsed_content)
    
    # lookup generic image based on keywords
    
    print(summarized_content)
    
        
    return {
        "message": "Autofill data received!",
        "title": suggested_title,
        "content": summarized_content,
        "cover_image": cover_image_url,
        "post_id": post_id
    }

@app.get("/posts")
async def get_posts(search: str) -> dict:
    if search != "":
        all_posts = posts.find({"title": {"$regex": search, "$options": "i"}}, {"_id": 0}).sort("modified_at", -1)
    else:
        all_posts = posts.find({}, {"_id": 0}).sort("modified_at", -1)
    return {"message": "Posts loaded successfully", "posts": list(all_posts)}

@app.get("/post/{id}")
async def get_post(id: str) -> dict:
    post = posts.find_one({"post_id": id}, {"_id": 0})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"message": "Post loaded successfully", "post": post}

@app.put("/edit")
async def edit_post(post_id: str = Form(...),
                    title: str = Form(...),
                    content: str = Form(...),
                    cover_image: UploadFile = File(None)) -> dict:
    
    post = posts.find_one({"post_id": post_id})
    
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # check if cover image was uploaded, in which case update the cover image
    if cover_image:
        upload_dir = "uploads"
        cover_id = f"{post_id}_cover.webp"
        upload_path = os.path.join(os.path.join(upload_dir, post_id), cover_id)
        
        # Delete the existing cover image to force an update
        if os.path.exists(upload_path):
            os.remove(upload_path)
        
        try:
            img = Image.open(BytesIO(await cover_image.read()))
            conv_img = img.convert("RGB")
            conv_img.save(upload_path, "webp")
            cover_image_url = cover_id
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error converting image: {e}")
    else:
        cover_image_url = post["cover_image"]
        
    print(cover_image)
        
    # update post content
    posts.update_one({"post_id": post_id},
                     {"$set": {"title": title,
                               "content": content,
                               "cover_image": cover_image_url,
                               "modified_at": datetime.now(timezone.utc)}})
    
    print(cover_image)
    
    return {"message": "Post updated successfully"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)