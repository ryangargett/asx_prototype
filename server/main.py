import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from decouple import config
from password_strength import PasswordPolicy
from pymongo import MongoClient

app = FastAPI()

client = MongoClient(config("MONGODB_KEY"))
db = client["main"]

print(db.list_collection_names())


pwd_policy = PasswordPolicy.from_names(
    length=8,
    uppercase=1,
    numbers=1,
    special=1
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RegisterRequest(BaseModel):
    username: str
    password: str
    
@app.get("/")
async def read_root():
    return {"message": "Welcome to the FastAPI application"}

def validate_password(password: str) -> tuple[bool, str]:
    
    """Validates a provided password against common password policies.

    Returns:
        bool: True if the password is valid, False otherwise
        error_msg (str): An error message if the password is invalid, an empty string otherwise
    """
    
    error_msg = []
    validation = pwd_policy.test(password)
    
    error_map = {
        "Length(8)": "Password must be at least 8 characters long",
        "Uppercase(1)": "Password must contain at least one uppercase letter",
        "Numbers(1)": "Password must contain at least one number",
        "Special(1)": "Password must contain at least one special character"
    }
    
    print(validation)
    
    for policy in validation:
        error_msg.append(error_map.get(str(policy), "Unknown policy violation"))
        
    if len(error_msg) > 0:
        return False, ", ".join(error_msg)
    else:
        return True, ""
        
    
@app.post("/register")
async def register(request: RegisterRequest):
    password = request.password
    
    is_valid, error_msg = validate_password(password)
    
    print(is_valid, error_msg)
    
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    else:
        return {"message": "User registered successfully"}
    
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
#