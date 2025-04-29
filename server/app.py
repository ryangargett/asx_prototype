import asyncio
import holidays
import mimetypes
import os
import json
import random
import regex as re
import requests
import shutil
import time
import uuid

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from fastapi import FastAPI, HTTPException, Depends, Response, Request, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from io import BytesIO
from pydantic import BaseModel
import pytz
from pytz import timezone as tz

import aiohttp
import uvicorn
import whisper

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.combining import AndTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
import boto3 as b3
from email_validator import validate_email, EmailNotValidError
#from decouple import config
from jose import jwt, JWTError
from markdown import markdown
from password_strength import PasswordPolicy
from passlib.context import CryptContext
from PIL import Image
from pymongo import MongoClient
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio


from summarizer import read_pdf, summarize_content, suggest_title, suggest_image_kwords
#from image_search import get_url_from_keyword

encrypter = CryptContext(schemes=["argon2"], deprecated="auto")

client = MongoClient(os.getenv("MONGODB_KEY"))

# Check if cluster is connected
try:
    client.admin.command('ping')
    print("MongoDB connection: Successful")
except Exception as e:
    print(f"MongoDB connection: Failed - {e}")

access_token = os.getenv("WEBFLOW_API_KEY")
collection_id = os.getenv("WEBFLOW_COLLECTION_ID")    

db = client["main"]
users = db["users"]
posts = db["posts"]
profiles = db["profiles"]
documents = db["documents_new"]
#documents.delete_many({})
stocks = db["stocks"]
users.delete_many({})
posts.delete_many({})

# check if s3 connection can be established
try:
    s3_client = b3.client("s3",
                        aws_access_key_id=os.getenv("AWS_ACCESS_KEY"),
                        aws_secret_access_key=os.getenv("AWS_SECRET_KEY"),   
                        region_name="ap-southeast-2")
except Exception as e:
    print(f"Error connecting to S3 bucket: {e}")
'''
users.insert_one({"username": "admin", 
                  "email": "",
                  "password": encrypter.hash("admin"),
                  "elevation": "admin"})
'''

webflow_access_token = os.getenv("WEBFLOW_API_KEY")

def _get_curr_time():
    return datetime.now(tz("Australia/Sydney"))

def _inside_trading_hours() -> bool:
    try:
        curr_time = _get_curr_time()
        curr_time_format = curr_time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"Checking trading hours at {curr_time_format} AEST")
        
        non_trading_dates = holidays.Australia(years=curr_time.year, observed=True)
    
        if curr_time.weekday() < 5 and curr_time.date() not in non_trading_dates:
            if curr_time.hour >= 10 and curr_time.hour <= 16:
                return True
    except Exception as e:
        print(f"Error encountered when checking trading hours: {e}")
    
    return False

def reset_daily_announcements() -> None:
    offset = 0
    page_limit = 100
    collected_all = False
    all_items = []
    announcement_collection_id = os.getenv("WEBFLOW_ANNOUNCEMENT_COLLECTION_ID")

    while not collected_all:
        try:
            response = requests.get(
            f"https://api.webflow.com/v2/collections/{announcement_collection_id}/items/live",
            headers = {
                "Authorization": "Bearer " + webflow_access_token,
                "Content-Type": "application/json"
            },
            params = {
                "offset": offset
            }
        )
            
        except Exception as e:
            print(f"Error uploading to webflow: {e}")

        all_items.extend(response.json()["items"])
        
        if len(response.json()["items"]) < page_limit:
            collected_all = True
        else:
            offset += page_limit
            
    if len(all_items) > 0:
        for item in all_items:
           delete_item(os.getenv("WEBFLOW_ANNOUNCEMENT_COLLECTION_ID"), item["id"])
    else:
        print(f"ERROR: No announcements found in collection {collection_id} to reset")
           
    print(f"Announcements successfully reset")

def get_hash(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            hash = sha256(f.read()).hexdigest()
        return hash
    except Exception as e:
        print(f"Error hashing file: {e}")
        return ""
    
'''
def create_from_feed(file_path: str, hash: str, ticker: str) -> None:
    try:
        post_id = str(uuid.uuid4())
        
        parsed_content = read_pdf(file_path)
        summarized_content = summarize_content(parsed_content)
        suggested_title = suggest_title(parsed_content)
        suggested_image_kwords = suggest_image_kwords(parsed_content)
        cover_image_url = get_url_from_keyword(suggested_image_kwords)
        
        created_at = datetime.now(timezone.utc)
        
        posts.insert_one({
            "post_id": post_id,
            "title": suggested_title,
            "content": summarized_content,
            "cover_image": cover_image_url if cover_image_url is not None else "GENERIC/PLACEHOLDER.svg",
            "created_at": created_at,
            "modified_at": created_at,
            "pdf_id": hash,
            #"sector": _get_sector_from_ticker(ticker)
        })

    except Exception as e:
        print(f"Error creating post from feed: {e}")
'''

async def generate_content(file_path: str, ticker: str) -> dict:
    
    try:
        print("Reading document...")
        parsed_content = read_pdf(file_path)
        
        summarize_task = summarize_content(parsed_content, ticker)
        
        summary_prompt = f"Provide a short (maximum 50 word) summary for the following announcement released from company {ticker}. This summary should be attractive and appropriate for a finance blog targeted towards beginner traders. This summary cannot include the ASX ticker in any way, only refer to the company by its' legal name (for example BHP GROUP LIMITED instead of ASX:BHP).\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUMMARY:"
        
        summary_task = summarize_content(parsed_content, ticker, prompt=summary_prompt)
        title_task = suggest_title(parsed_content, ticker)
        
        document_content, summary, (short_title, long_title) = await asyncio.gather(
            summarize_task, summary_task, title_task
        )
        
        print(document_content)
        print(summary)
        print(short_title, long_title)
        
        print("Document processed successfully")
    except Exception as e:
        print(f"Error generating content: {e}")
    
    content =  {
        "short_title": short_title,
        "long_title": long_title,
        "content": document_content,
        "summary": summary
    }
    
    return content

def get_stock_data(ticker: str) -> dict:
    stock_data = None
    
    ticker_elements = ticker.split(":")
    if len(ticker_elements) > 1:
        ticker = ticker_elements[1] + ".AX"
    else:
        ticker = ticker + ".AX"
    
    details = stocks.find_one({"ticker": ticker})
    if details:
        
        print(details)
        
        sector = details.get("sector", "N/A")
        
        if "oil & gas" in details.get("industry", "").lower():
            industry = "Oil & Gas"
        elif "industrial metals" in details.get("industry", "").lower():
            industry = "Industrial Metals"
        elif "precious metals" in details.get("industry", "").lower():
            industry = "Precious Metals"
        elif "lumber" in details.get("industry", "").lower():
            industry = "Lumber"
        elif "packaging" in details.get("industry", "").lower():
            industry = "Packaging"
        elif "machinery" in details.get("industry", "").lower():
            industry = "Heavy Machinery"
        elif "construction" in details.get("industry", "").lower():
            industry = "Construction"
        elif re.search(r"chemical*", details.get("industry", ""), re.IGNORECASE):
            industry = "Chemicals"
        elif re.search(r"biotech*", details.get("industry", ""), re.IGNORECASE):
            industry = "Biotech"
        elif "freight" in details.get("industry", "").lower():
            industry = "Logistics"
        elif re.search(r"agricultu*|farm*", details.get("industry", ""), re.IGNORECASE):
            industry = "Agriculture"
        elif "silver" in details.get("industry", "").lower():
            industry = "Silver"
        elif "uranium" in details.get("industry", "").lower():
            industry = "Uranium"
        elif "coal" in details.get("industry", "").lower():
            industry = "Coal"
        elif "copper" in details.get("industry", "").lower():
            industry = "Copper"
        elif "gold" in details.get("industry", "").lower():
            industry = "Gold"
        elif "steel" in details.get("industry", "").lower():
            industry = "Steel"
        elif "aluminum" in details.get("industry", "").lower():
            industry = "Aluminum"
        elif re.search(r"renewable*", details.get("industry", ""), re.IGNORECASE):
            industry = "Renewables"        
        else:
            industry = "Other"
        
        return {
            "sector": sector,
            "industry": industry
        }
    
    return stock_data

def _get_collection_size(collection_id: str) -> int:
    offset = 0
    page_limit = 100
    collected_all = False
    all_items = []

    while not collected_all:

        try:
            response = requests.get(
            f"https://api.webflow.com/v2/collections/{collection_id}/items/live",
            headers = {
                "Authorization": "Bearer " + webflow_access_token,
                "Content-Type": "application/json"
            },
            params = {
                "offset": offset
            }
        )
            
        except Exception as e:
            print(f"Error uploading to webflow: {e}")

        all_items.extend(response.json()["items"])
        
        if len(response.json()["items"]) < page_limit:
            collected_all = True
        else:
            offset += page_limit
            
    num_articles = len(all_items)
    return 0 if num_articles is None else num_articles

def push_to_collection(collection_id: str, payload: dict) -> None:
    try:
        response = requests.post(
            f"https://api.webflow.com/v2/collections/{collection_id}/items/live",
            headers = {
                "Authorization": "Bearer " + webflow_access_token,
                "Content-Type": "application/json"
            },
            json = {
                "fieldData": payload
            }
        )
        
        print(response.json())
            
    except Exception as e:
        print(f"Error uploading to webflow: {e}")

async def search_collection(collection_id: str, search_query: str, field: str = "name") -> str:
    offset = 0
    page_limit = 100
    collected_all = False
    all_items = []

    while not collected_all:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.webflow.com/v2/collections/{collection_id}/items/live",
                    headers={
                        "Authorization": "Bearer " + webflow_access_token,
                        "Content-Type": "application/json"
                    },
                    params={"offset": offset}
                ) as response:
                    response_data = await response.json()
                    all_items.extend(response_data["items"])
                    
                    if len(response_data["items"]) < page_limit:
                        collected_all = True
                    else:
                        offset += page_limit
        except Exception as e:
            print(f"Error fetching collection: {e}")
            return None

    item_id = None
    for item in all_items:
        if item["fieldData"][field] == search_query:
            return item["id"]
    
    print(f"ERROR: No item found in collection {collection_id} with search term {search_query}") 
    return item_id
        

def _get_url_from_bucket(bucket: str) -> str:
    url = "https://rtwimages.s3.ap-southeast-2.amazonaws.com/PLACEHOLDER.png"    
    response = s3_client.list_objects_v2(
        Bucket = "rtwimages",
        Prefix = f"{bucket}/",
    )
    
    images = response.get("Contents", [])
    if len(images) > 1:
        images = images[1:] # avoid selecting base folder as index
    
    try:
        random_image = random.choice(images)
        image_key = random_image["Key"]
        url = f"https://rtwimages.s3.ap-southeast-2.amazonaws.com/{image_key}"
        
        print(f"Image URL: {url}")
    except Exception as e:
        print(f"Error fetching image URL from bucket: {e}, using default....")
        
    return url
    
async def get_cover_image(industry: str) -> str:

    #TODO: Significantly expand this system

    if "oil & gas" in industry.lower():
        bucket = "oilandgas"
    elif "renewable" in industry.lower():
        bucket = "renewables"
    elif "uranium" in industry.lower():
        bucket = "nuclear"
    elif "chemical" in industry.lower():
        bucket = "chemicals"
    elif "coal" in industry.lower():
        bucket = "coal"
    elif "lumber" in industry.lower():
        bucket = "lumber"
    elif "packaging" in industry.lower():
        bucket = "packaging"
    elif "gold" in industry.lower():
        bucket = "gold"
    elif "steel" in industry.lower():
        bucket = "steel"
    elif "agriculture" in industry.lower():
        bucket = "agriculture"
    elif "construction" in industry.lower():
        bucket = "construction"
    elif "biotech" in industry.lower():
        bucket = "biotech"
    elif "logistics" in industry.lower():
        bucket = "logistics"
    elif "silver" in industry.lower():
        bucket = "silver"
    else:
        bucket = "mining"
    
    url = _get_url_from_bucket(bucket)
    
    return url

def push_announcement_to_site(hash: str, datetime: str, ticker: str, formal_title: str, market_sensitive: bool, is_cash_flow: bool, is_substantial: bool) -> None:
    
    #TODO: Reimplement once cms collection size cap has been increased, for now just use raw ticker
    
    #ticker_collection_id = os.getenv("WEBFLOW_TICKER_COLLECTION_ID")
    #ticker_id = search_collection(ticker_collection_id, ticker)
    
    if market_sensitive:
        item_colour = "#FFBF00"
    else:
        item_colour = "#FFFFFF"
    
    fieldData = {
        "name": hash,
        "announcement-datetime": datetime,
        "announcement-title": formal_title,
        "announcement-company": ticker,
        "announcement-url": f"https://rtwasxreports.s3.ap-southeast-2.amazonaws.com/{hash}.pdf",
        "market-sensitive": market_sensitive,
        "cash-flow": is_cash_flow,
        "substantial": is_substantial,
        "item-colour": item_colour, # there's probably a way better way of doing this, but it works so I'm keeping it for now
        
    }
    
    announcement_collection_id = os.getenv("WEBFLOW_ANNOUNCEMENT_COLLECTION_ID")
    
    push_to_collection(announcement_collection_id, fieldData)

def delete_item(collection_id: str, item_id: str) -> None:
    # need to unpublish the live item first to completely drop it from the collection
    try:
            response = requests.delete(
            f"https://api.webflow.com/v2/collections/{collection_id}/items/{item_id}/live",
            headers = {
                "Authorization": "Bearer " + webflow_access_token,
                "Content-Type": "application/json"
            }
        )
    except Exception as e:
        print(f"Error dropping live item from webflow: {e}")
        
    try:
            response = requests.delete(
            f"https://api.webflow.com/v2/collections/{collection_id}/items/{item_id}",
            headers = {
                "Authorization": "Bearer " + webflow_access_token,
                "Content-Type": "application/json"
            }
        )
    except Exception as e:
        print(f"Error deleting from webflow: {e}")

def drop_oldest(collection_id: str) -> None:
    offset = 0
    page_limit = 100
    collected_all = False
    all_items = []
    
    while not collected_all:

        try:
            response = requests.get(
            f"https://api.webflow.com/v2/collections/{collection_id}/items/live",
            headers = {
                "Authorization": "Bearer " + webflow_access_token,
                "Content-Type": "application/json"
            },
            params = {
                "offset": offset
            }
        )
            
        except Exception as e:
            print(f"Error uploading to webflow: {e}")

        all_items.extend(response.json()["items"])
        
        if len(response.json()["items"]) < page_limit:
            collected_all = True
        else:
            offset += page_limit
            
    oldest_item_id = all_items[-1]["id"]
    
    delete_item(collection_id, oldest_item_id)
    
def _get_industry_group(industry: str) -> str:
    if industry in ["Aluminum", "Copper", "Gold", "Industrial Metals", "Precious Metals", "Silver", "Steel"]:
        return "Metals and Mining"
    elif industry in ["Lumber"]:
        return "Forestry and Paper Products"
    elif industry in ["Coal", "Oil and Gas"]:
        return "Consumables"
    elif industry in ["Green Energy", "Uranium"]:
        return "Renewables"
    elif industry in ["Construction", "Heavy Machinery"]:
        return "Construction Materials"
    elif industry in ["Agriculture", "Biotech", "Chemicals"]:
        return "Industrial Chemicals"
    elif industry in ["Logistics", "Packaging"]:
        return "Containers and Packaging"
    else:
        return "Consumables" # default case]
    
async def push_article_to_site(file_path: str, announcement_hash: str, formatted_datetime: str, ticker: str, formal_title: str, max_articles: int = 6000) -> None:
    collection_id = os.getenv("WEBFLOW_ARTICLE_COLLECTION_ID")
    print(file_path, announcement_hash, formatted_datetime, ticker, formal_title)
    
    try:
        # Check if the article already exists in the site
        article_id = await search_collection(collection_id, announcement_hash, "hash-value")
        if article_id:
            print(f"ERROR: Attempted publication failed due to pre-existing article on website, skipping....")
            return
        
        num_articles = _get_collection_size(collection_id)
        if num_articles is not None and num_articles > max_articles:
            print(f"ERROR: Article threshold reached, deleting oldest article to make room....")
            drop_oldest(collection_id)
            
        stock_data = get_stock_data(ticker)

        # Concurrently generate content and search collections for relevant IDs
        generated_content_task = generate_content(file_path, ticker)
        sector_search_task = search_collection(os.getenv("WEBFLOW_SECTOR_COLLECTION_ID"), stock_data["sector"])
        industry_search_task = search_collection(os.getenv("WEBFLOW_INDUSTRY_COLLECTION_ID"), stock_data["industry"])
        industry_group_search_task = search_collection(os.getenv("WEBFLOW_INDUSTRY_GROUP_COLLECTION_ID"), _get_industry_group(stock_data["industry"]))
        ticker_search_task = search_collection(os.getenv("WEBFLOW_STOCK_COLLECTION_ID"), "ASX:" + ticker)
        suggest_cover_image_task = get_cover_image(stock_data["industry"])

        # Await all tasks concurrently
        generated, sector_id, industry_id, industry_group_id, ticker_id, cover_image = await asyncio.gather(
            generated_content_task, sector_search_task, industry_search_task, industry_group_search_task, ticker_search_task, suggest_cover_image_task
        )
        
        print(stock_data)
        
    finally:
        # Clean up the temporary file
        if os.path.exists(file_path):
            os.remove(file_path)

    print("Attempting webflow upload...")

    if generated and stock_data:
        fieldData = {
            "name": generated["short_title"],
            "article-datetime": formatted_datetime,
            "title": generated["long_title"],
            "short-title": generated["short_title"],
            "formal-title": formal_title,
            "content": generated["content"],
            "hash-value": announcement_hash,
            "summary": generated["summary"],
            "image-url": cover_image,
            "document-url": f"https://rtwasxreports.s3.ap-southeast-2.amazonaws.com/{announcement_hash}.pdf",
            "article-sector": sector_id,
            "article-industry": industry_id,
            "article-ticker": ticker_id,
            "article-industry-group": industry_group_id
        }
        
        # Push the article to the collection
        push_to_collection(collection_id, fieldData)
        
    else:
        print("Error: malformed content or stock data, skipping upload...")
        
def _format_datetime(unformatted_datetime: str) -> str:
    try:
        dt = datetime.strptime(unformatted_datetime, '%d-%b-%Y %H:%M:%S')
        
        # localize to proper timezone specified in the api (AWST)
        api_local_tz = pytz.timezone('Australia/Perth')
        dt_local = api_local_tz.localize(dt)
        
        dt_utc = dt_local.astimezone(pytz.UTC)
        formatted_datetime = dt_utc.isoformat()
        return formatted_datetime
    except ValueError as e:
        print(f"Error parsing datetime string: {e}")
async def announcement_task_wrapper(announcement: dict, progress_bar: tqdm) -> None:
    try:
        await process_announcement(announcement)
    except Exception as e:
        print(f"Error processing announcement {announcement.get('fileId', 'NA')}: {e}")
    finally:
        progress_bar.update(1)

async def process_announcement(announcement: dict) -> None:
    """
    This function processes an individual announcement concurrently by validating,
    generating article content, and pushing it to Webflow asynchronously.
    """
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/pdf,application/x-pdf,*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }
    
    legal_tickers = ["29M", "A11", "A1M", "A4N", "AAI", "AAR", "ADT", "AEE", "AEL", "AGE", "AIS", "AKM", "ALD", "ALK", "AMC", "AMI", "ARR", "ARU", "ASL", "ATR", "AUC", "AVL", "AZY", "BC8", "BCI", "BCK", "BCN", "BGL", "BHP", "BIS", "BKW", "BKY", "BMN", "BOC", "BOE", "BPT", "BRE", "BRI", "BRL", "BSL", "BTR", "CAA", "CAY", "CHN", "CIA", "CMM", "COI", "CRD", "CRN", "CSC", "CTM", "CVN", "CVV", "CXO", "CYL", "DEG", "DGL", "DLI", "DRR", "DRX", "DVP", "DYL", "EEG", "EGR", "EMR", "ENR", "EQR", "ERA", "ETM", "EVN", "FEX", "FFM", "FMG", "GG8", "GMD", "GNG", "GOR", "GRR", "GRX", "HCH", "HRZ", "HZN", "IGO", "ILU", "IMA", "IMD", "INR", "IPL", "IPX", "JHX", "JMS", "KAR", "KCN", "KLL", "LCY", "LIN", "LLL", "LOT", "LRV", "LTR", "LYC", "MAC", "MAH", "MAU", "MDX", "MEI", "MEK", "MGX", "MIN", "MLX", "MM8", "MMI", "MRL", "NEM", "NHC", "NIC", "NMG", "NST", "NTU", "NUF", "NXG", "OBM", "OMA", "OMH", "ORA", "ORI", "ORN", "PDI", "PDN", "PEN", "PGH", "PLS", "PMT", "PNR", "POL", "PRG", "PRN", "PRU", "PTN", "PTR", "QGL", "QPM", "RHI", "RIO", "RMS", "RND", "RNU", "RRL", "RSG", "RXL", "S32", "SBM", "SFR", "SGM", "SMI", "SMR", "SPR", "STA", "STK", "STO", "STX", "SVL", "SVM", "SX2", "SYA", "SYR", "TBN", "TBR", "TCG", "TGM", "TLG", "TTM", "TTT", "TVN", "TZN", "USL", "VAU", "VEA", "VSL", "VUL", "VYS", "WA1", "WAF", "WC8", "WDS", "WGN", "WGX", "WHC", "WIA", "YAL", "ZIM"] 
    
    file_id = announcement.get("fileId", "")
    
    if not file_id:
        print(f"Skipping announcement {announcement.get('dateTime', 'N/A')} due to malformed content")
        return

    f_name = f"./{file_id}.pdf"

    try: # check to see if document already exists in the database and is properly formed before downloading from API
        if not documents.find_one({"file_id": file_id}):
            if announcement.get("documentURL", "N/A") != "N/A":
                response = requests.get(announcement["documentURL"], headers=headers, auth=(os.getenv("ASX_API_USERNAME"), os.getenv("ASX_API_PASSWORD")))
                
                with open(f_name, "wb") as f:
                    f.write(response.content)
                
                announcement_hash = get_hash(f_name)
                
                try:
                    s3_client.upload_file(f_name, "rtwasxreports", f"{announcement_hash}.pdf", ExtraArgs={"ContentType": "application/pdf"})
                except Exception as e:
                    print(f"Error uploading file to S3: {e}")
                    return

                # generate formatted datetime for article stamp
                formatted_datetime = _format_datetime(announcement["dateTime"])
        
                is_cash_flow = True if (("cash" in announcement["heading"].lower()) or ("cashflow" in announcement["heading"].lower())) else False
                is_substantial = True if "substantial" in announcement["heading"].lower() else False
                    
                push_announcement_to_site(announcement_hash, formatted_datetime, announcement["code"], announcement["heading"], announcement["isSensitive"] == "Y", is_cash_flow, is_substantial)

                #TODO: Improve filtering mechanism to avoid unnecessary uploads
                if announcement.get("isSensitive", "N") == "Y" and announcement.get("code", "") in legal_tickers:
                    print("Discovered legal entry!")                                 
                    asyncio.create_task(
                        push_article_to_site(
                            f_name, announcement_hash, formatted_datetime, announcement["code"], announcement["heading"] # create new process for article generation to ensure announcements are kept up-to-date
                        )
                    )
            
                documents.insert_one(
                    {
                        "file_id": announcement["fileId"],
                        "title": announcement["heading"],
                        "hash": announcement_hash,
                        "date_released": announcement["dateTime"],
                        "price_sensitive": announcement["isSensitive"],
                        "linked_ticker": announcement["code"],
                        "news_types": announcement["newsTypes"],
                        "prev_ticker": announcement["releaseCode"] if announcement.get("releaseCode", "") != "" else "N/A",
                    }
                )
                
        else:
            print(f"Announcement {announcement['fileId']} already exists in database, skipping download process.")
            
    except Exception as e:
        print(f"Error validating announcement {announcement['fileId']}: {e}")
                   
async def renew_announcements() -> None:
    curr_time = _get_curr_time()
    curr_time_formatted = curr_time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"Reviewing new announcements at {curr_time_formatted} AEST")
    
    username = os.getenv("ASX_API_USERNAME")
    password = os.getenv("ASX_API_PASSWORD")
        
    try:
        daily_announcements = requests.get(
            "https://quoteapi.com/files/rtw/asx_news_today.json", 
            auth=(username, password)
        )
        print(f"Polled at {curr_time_formatted} AEST")
        
        daily_announcements = list(daily_announcements.json())
        
        last_announcement = daily_announcements[0]
        if documents.find_one({"file_id": last_announcement["fileId"]}):
            print(f"No new announcements found since last poll, skipping....")
        else:
            print(f"New announcements found, processing....")
            daily_announcements.reverse()
            
            progress_bar = tqdm(total=len(daily_announcements), desc="Processing announcements")
            
            announcement_processing_tasks = []
            for instance in daily_announcements:
                if instance.get("heading", "end of day").lower() != "end of day":
                    announcement_processing_tasks.append(announcement_task_wrapper(instance, progress_bar))
            
            await tqdm_asyncio.gather(*announcement_processing_tasks)
    except Exception as e:
        print(f"Unexpected error encountered when polling ASX announcements: {e}")
        
        curr_time = _get_curr_time()
        
        if curr_time.weekday() < 4: # Monday to Thursday, we keep announcements over the weekend
            if curr_time.hour >= 23 and curr_time.minute >= 30:
                print(f"End of trading day, resetting announcements....")
                reset_daily_announcements()
        else:
            print(f"Day is not a trading day, skipping reset....")

@asynccontextmanager
async def lifespan(app: FastAPI):
    
    print("Starting FastAPI application...")
    
    scheduler = AsyncIOScheduler(
        timezone = "Australia/Sydney"
    )
    
    # ASX Announcement polling (trading days only)
    scheduler.add_job(
        renew_announcements,
        "cron",
        day_of_week="mon,tue,wed,thu,fri",
        hour="0-23",
        minute="*",
        max_instances=1
    )
    
    # Daily reset (23:30 on trading days)
    scheduler.add_job(
        reset_daily_announcements,
        "cron",
        day_of_week="mon,tue,wed,thu",
        hour=23,
        minute=30,
        max_instances=1
    )
    
    scheduler.start()
    yield
    
    scheduler.shutdown(wait=False)

'''
pwd_policy = PasswordPolicy.from_names(
    length=8,
    uppercase=1,
    numbers=1,
    special=1
)
'''

app = FastAPI(lifespan=lifespan)
#app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

'''
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

class TickerRequest(BaseModel):
    search_query: str    

def generate_token(username: str, elevation: str, expiry: int) -> str:
    encode = {"user": username,
              "elevation": elevation, 
              "exp": datetime.now(timezone.utc) + timedelta(minutes=expiry)}
    return jwt.encode(encode, os.getenv("SECRET_KEY"), algorithm = os.getenv("AUTH_ALGORITHM"))

def verify_token(token: str):
    try:
        payload = jwt.decode(token, os.getenv("SECRET_KEY"), algorithms=[os.getenv("AUTH_ALGORITHM")])
        username = payload.get("user")
        exp = payload.get("exp")
        current_time = datetime.now(timezone.utc).timestamp()
        
        #print(f"Token expiration time: {exp}")
        #print(f"Current time: {current_time}")
        if username is None:
            raise HTTPException(status_code=403, detail="Invalid token")
        return payload
    except JWTError:
        raise HTTPException(status_code=403, detail="Invalid token")
    
def transcribe_video(video_path: str) -> str:
    try:
        model = whisper.load_model("base.en")
        options = whisper.DecodingOptions(language="en")
        transcription = model.transcribe(video_path)
        return transcription["text"]
    except Exception as e:
        print(f"Error transcribing video: {e}")
        raise HTTPException(status_code=500, detail=f"Error transcribing video: {e}")
''' 
    
@app.get("/")
async def read_root():
    return {"message": "Welcome to the FastAPI application"}

'''
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
    
    if not user:
        # try email address as well
        user = users.find_one({"email": request.username})
        
        if not user:
            raise HTTPException(status_code=400, detail="Invalid username or email")
        
    if not verify_password(request.password, user["password"]):
        raise HTTPException(status_code=400, detail="Invalid password")
    
    auth_token = generate_token(user["username"], user["elevation"], int(os.getenv("TOKEN_EXPIRY")))
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
    
    upload_dir = os.getenv("UPLOAD_DIR")
    
    print(post_id)
    
    if not post_id:
        post_id = str(uuid.uuid4())
        
    os.makedirs(os.path.join(upload_dir, post_id), exist_ok=True)

    # ensure file can be coerced to .webp before uploading to db
    
    cover_id = f"{post_id}_cover.webp"
    upload_path = os.path.join(os.path.join(upload_dir, post_id), cover_id)
    
    print(os.getenv("DEF_IMAGE"))
    print(cover_image_url)
    
    if cover_image: # if a custom image is provided, upload to server for conversion
        try:
            img = Image.open(BytesIO(await cover_image.read()))
            conv_img = img.convert("RGB")
            conv_img.save(upload_path, "webp")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error converting image: {e}")
    else:
        if cover_image_url != "http://localhost:8000/uploads/GENERIC/PLACEHOLDER.svg":
            try:
                img = Image.open(BytesIO(requests.get(cover_image_url).content))
                conv_img = img.convert("RGB")
                conv_img.save(upload_path, "webp")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error converting image: {e}")
        else:
            cover_id = os.getenv("DEF_IMAGE")
    
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
async def autofill_data(file: UploadFile = File(...),
                        user_prompt: str = Form(...)) -> dict:
    
    upload_dir = os.getenv("UPLOAD_DIR")
    
    post_id = str(uuid.uuid4())
    post_dir = os.path.join(upload_dir, post_id)
    os.makedirs(post_dir, exist_ok=True)
    file_path = os.path.join(post_dir, file.filename)
    
    try:
        with open(file_path, "wb") as in_file:
            in_file.write(await file.read())
            
        file_type, _ = mimetypes.guess_type(file_path)
        if file_type == "application/pdf":
            parsed_content = read_pdf(file_path)
            summarized_content = markdown(summarize_content(parsed_content, user_prompt))
            suggested_title = suggest_title(parsed_content)
            #suggested_sector = suggested_sector(parsed_content)
            suggested_image_kwords = suggest_image_kwords(parsed_content)
            cover_image_url = get_url_from_keyword(suggested_image_kwords)
        elif file_type.startswith("video"):
            with open(file_path, "r") as in_file:
                parsed_content = transcribe_video(file_path)
                summarized_content = markdown(summarize_content(parsed_content, user_prompt))
                suggested_title = suggest_title(parsed_content)
                #suggested_sector = suggested_sector(parsed_content)
                suggested_image_kwords = suggest_image_kwords(parsed_content)
                cover_image_url = get_url_from_keyword(suggested_image_kwords)
        else:
            raise HTTPException(status_code=400, detail="Invalid file type")
        
            
        return {
            "message": "Autofill data received!",
            "title": suggested_title if suggested_title else "Untitled",
            "content": summarized_content if summarized_content else "No content",
            "cover_image": cover_image_url,
            "post_id": post_id
        }
    
    except Exception as e:
        if os.path.exists(file_path):
                os.remove(file_path)
        if os.path.exists(post_dir):
            shutil.rmtree(post_dir)
        raise HTTPException(status_code=500, detail=f"Error processing file: {e}")
                          
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
    
    document = documents.find_one({"hash": post["pdf_id"]}, {"_id": 0})
    if document:
        temp_url = s3_client.generate_presigned_url("get_object", 
                                                    Params={
                                                        "Bucket": "rtwasxreports", 
                                                        "Key": f"{document['hash']}.pdf",
                                                        "ResponseContentDisposition": "inline",
                                                        "ResponseContentType": "application/pdf"
                                                    },
                                                    ExpiresIn=3600)
        print(temp_url)
        post["pdf_url"] = temp_url
    
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

@app.get("/update_videos")
async def update_videos() -> dict:
    
    next_page_token = ""
    videos_collection = db["videos"]
    
    while next_page_token is not None:
        response = requests.get(
            f"https://www.googleapis.com/youtube/v3/playlistItems?key={os.getenv('YOUTUBE_API_KEY')}&playlistId={os.getenv('PLAYLIST_ID')}&part=snippet&pageToken={next_page_token}"
        )
        playlist_metadata = response.json()
        video_metadata = playlist_metadata.get("items", [])
        if video_metadata:
            for video in video_metadata:
                video_id = video["snippet"]["resourceId"]["videoId"]
                existing_video = videos_collection.find_one({"snippet.resourceId.videoId": video_id})
                
                if existing_video:
                    # Update existing video metadata
                    videos_collection.update_one({"snippet.resourceId.videoId": video_id}, {"$set": video})
                else:
                    # Insert new video metadata
                    videos_collection.insert_one(video)
                    
        next_page_token = playlist_metadata.get("nextPageToken")
    
    return {"message": "Videos updated successfully"}
                
@app.get("/cached_videos")
async def get_cached_videos() -> dict:
    videos_collection = db["videos"]    
    cached_videos = list(videos_collection.find({}, {"_id": 0}))
    return {"message": "Videos fetched successfully", "videos": cached_videos}


@app.put("/update_stocks")
async def update_stocks() -> dict:
    tickers = get_asx_tickers()
    print(f"Discovered {len(tickers)} ASX-listed companies.")
    stocks_collection = db["stocks"]
    
    for ticker_idx, ticker in enumerate(tickers):
        print(f"Processing {ticker} {ticker_idx} / {len(tickers)}")
        existing_stock = stocks_collection.find_one({"ticker": ticker})
        if not existing_stock:
            time.sleep(0.1) # ensure server doesn't time out
            stock = get_company_info(ticker)
            if stock:
                stocks_collection.insert_one(stock)
        else:
            print(f"Found existing metadata for {ticker}, skipping....")
        
        stock = get_company_info(ticker)
        
    return {"message": "Stocks updated successfully"}

@app.post("/get_tickers")
async def get_tickers(request: TickerRequest) -> dict:
    search_query = request.search_query.lower()
    print(search_query)
    stocks_collection = db["stocks"]
    
    valid_tickers = []
    
    if search_query != "":
        exact_matches = list(stocks_collection.find({"$or": [{"ticker": search_query}, {"company_name": search_query}]}, {"_id": 0}))
        print(exact_matches)
        if exact_matches:
            valid_tickers = exact_matches
        else:
            valid_tickers += list(stocks_collection.find({"ticker": {"$regex": search_query, "$options": "i"}}, {"_id": 0}))
            valid_tickers += list(stocks_collection.find({"company_name": {"$regex": search_query, "$options": "i"}}, {"_id": 0}))
            
    if len(valid_tickers) > 5:
        valid_tickers = valid_tickers[:5]        
    
    print(valid_tickers)

    return {"message": "Stocks fetched successfully", "tickers": valid_tickers}
'''

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)