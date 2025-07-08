import asyncio
import async_timeout
import json
import numpy as np
import math
import os
import pytz
import random
import regex as re
import requests

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from dateutil.parser import parse
from hashlib import sha256
from pytz import timezone as tz

import httpx
import uvicorn

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asyncio import Semaphore
import boto3 as b3
from fastapi import FastAPI
from jinja2 import Environment, FileSystemLoader
import matplotlib.pyplot as plt
from mjml import mjml_to_html
from pymongo import MongoClient
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio
from tweepy.asynchronous import AsyncClient
from unidecode import unidecode

from dotenv import load_dotenv
load_dotenv()

jinja_env = Environment(loader=FileSystemLoader("./data/templates"))
article_summary_template = jinja_env.get_template("article_summary.mjml.j2")
announcement_alert_template = jinja_env.get_template("announcement_alert.mjml.j2")
announcement_alert_summary_template = jinja_env.get_template("announcement_alert_summary.mjml.j2")

reset_executor = ThreadPoolExecutor(max_workers=1)
email_executor = ThreadPoolExecutor(max_workers=1)

announcement_semaphore = Semaphore(10)
asx_download_semaphore = Semaphore(2)

from summarizer import read_pdf, summarize_content
from metals import update_metal_prices
from logging_init import logger

mongo_client = MongoClient(os.getenv("MONGODB_KEY"))

# Check if cluster is connected
try:
    mongo_client.admin.command('ping')
    logger.info("MongoDB connection successful")
except Exception as e:
    logger.error(f"MongoDB connection failed - {e}")

access_token = os.getenv("WEBFLOW_API_KEY")
collection_id = os.getenv("WEBFLOW_COLLECTION_ID")

num_sensitive = 0

db = mongo_client["main"]
documents = db["documents_new_3"]
stocks = db["stocks"]
articles = db["articles"]
metals = db["metals"]
db['metals'].aggregate([{"$out": "metals_backup"}])
alerts = db["alerts"]

# check if s3 connection can be established
try:
    s3_client = b3.client("s3",
                        aws_access_key_id=os.getenv("AWS_ACCESS_KEY"),
                        aws_secret_access_key=os.getenv("AWS_SECRET_KEY"),   
                        region_name="ap-southeast-2")
    logger.info("AWS connection successful")
except Exception as e:
    logger.error(f"AWS connection failed: {e}")

# check if twitter connection can be established
try:
    twitter_client = AsyncClient(
        os.getenv("TWITTER_BEARER_TOKEN"),
        os.getenv("TWITTER_API_KEY"),
        os.getenv("TWITTER_API_SECRET"),
        os.getenv("TWITTER_ACCESS_TOKEN"),
        os.getenv("TWITTER_ACCESS_SECRET")
    )
    logger.info("Twitter connection successful")
except Exception as e:
    logger.error(f"Twitter connection failed: {e}")

webflow_access_token = os.getenv("WEBFLOW_API_KEY")

def get_email_list() -> list[dict]:
    """Returns a list of email addresses from Memberstack, filtered to only include those with email alerts enabled
    """
    
    headers = {
        "X-API-KEY": os.getenv("MEMBERSTACK_API_KEY"),
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(
            "https://admin.memberstack.com/members", headers=headers)
        
        response.raise_for_status()
        response = response.json()
        
        member_data = response.get("data", {})
        if member_data:
            
            emails = set()
            legal_emails = []
            
            for member in member_data:
                alerts_enabled = member["customFields"].get("email-alerts", "false")
                if alerts_enabled == "true":
                    address = member["auth"]["email"]
                    if address not in emails:
                        emails.add(address)
                        legal_emails.append({
                            "name": member["customFields"].get("first-name", ""),
                            "address": address
                            })
                else:
                    logger.warning("Received invalid member data from Memberstack")
                
    except Exception as e:
        logger.error(f"Unexpected error getting email list: {e}")
        
    return legal_emails

def cache_collection(collection_id: str, key_field: str, cache_path: str) -> dict:
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            cached_collection = json.load(f) 
    else:
        offset = 0
        page_limit = 100
        collected_all = False
        cached_items = {}

        while not collected_all:
            try:
                response = requests.get(
                    f"https://api.webflow.com/v2/collections/{collection_id}/items/live",
                    headers = {
                        "Authorization": "Bearer " + access_token,
                        "Content-Type": "application/json"
                    },
                    params = {
                        "offset": offset
                    }
                )
                
                response.raise_for_status()
                items = response.json()["items"]

                for item in items:
                    if key_field == "id":
                        entry = item["id"]
                    else:
                        entry = item["fieldData"][key_field]
                        
                    cached_items[entry] = item

                if len(items) < page_limit:
                    collected_all = True
                else:
                    offset += page_limit
            except Exception as e:
                logger.error(f"Failure downloading from webflow collection: {e}")
        
        cached_collection = dict(sorted(cached_items.items()))
        
        with open(cache_path, "w") as f:
            json.dump(cached_collection, f, indent = 4)
        
    return cached_collection

all_stocks = cache_collection(os.getenv("WEBFLOW_STOCK_COLLECTION_ID"), "ticker", "./data/cached_stocks.json")
all_industries = cache_collection(os.getenv("WEBFLOW_INDUSTRY_COLLECTION_ID"), "id", "./data/cached_industries.json")
all_industry_groups = cache_collection(os.getenv("WEBFLOW_INDUSTRY_GROUP_COLLECTION_ID"), "id", "./data/cached_industry_groups.json")

def _get_missing_stocks(file_path: str = "./data/missing_stocks.json") -> None:
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            missing_stocks = json.load(f)
    else:
        missing_stocks = {
            "tickers": []
        }
        
    return missing_stocks

if all_stocks and all_industries and all_industry_groups:
    logger.info("Successfully loaded all stocks and industries from cache")
    
mailgun_key = os.getenv("MAILGUN_KEY")
if not mailgun_key:
    logger.error("MAILGUN_KEY environment variable is missing. Cannot send email.")
else:
    logger.info("Successfully loaded mailgun key from cache")
    
def get_legal_tickers() -> None:
    if os.path.exists("./data/legal_tickers.json"):
        with open("./data/legal_tickers.json") as f:
            legal_tickers = json.load(f)
    else:
        legal_tickers = []
        for stock in all_stocks:
        
            industry_group = None
            
            industry_group_id = all_stocks[stock]["fieldData"]["company-industry-group"]
            industry_group = all_industry_groups[industry_group_id]["fieldData"]["name"]
            if industry_group in ["Consumables", "Metals and Mining", "Renewables"]:
                legal_tickers.append(all_stocks[stock]["fieldData"]["ticker"])
                
        with open("./data/legal_tickers.json", "w") as f:
            json.dump(legal_tickers, f, indent = 4)
            
    return legal_tickers
            
legal_tickers = get_legal_tickers()

if legal_tickers:
    logger.info("Successfully loaded legal tickers from cache")
def _get_curr_time():
    return datetime.now(tz("Australia/Sydney"))

def email_content(content: str, title: str) -> None:
    
    emails = get_email_list()
    
    for email in emails:
    
        response = requests.post(
                    "https://api.mailgun.net/v3/rockstocks.ai/messages",
                    auth=("api", mailgun_key),
                    data={
                        "from": "Mailgun Sandbox <postmaster@rockstocks.ai>",
                        "to": f"<{email['address']}>",
                        "subject": f"{email['name']} - {title}",
                        "html": content
                    }
                )
        logger.info(f"Mailgun response status: {response.status_code}")
        
        if response.ok:
            logger.info("Email sent successfully.")
        else:
            logger.error(f"Failed to send email. Response: {response.text}")

def collect_for_email(max_articles: int = 10) -> None:
    logger.info("Starting email collection task")
    num_overflow = 0

    try:
        collated_articles = list(articles.find({}).sort("datetime", -1))
        logger.info(f"Fetched {len(collated_articles)} collated articles from the database.")

        email_list = []
        for article in collated_articles:
            email_list.append(article)
            
        if len(email_list) > max_articles:
            email_list = email_list[:max_articles]
            num_overflow = len(collated_articles) - max_articles

        mjml_src = article_summary_template.render(
            articles = email_list,
            num_overflow = num_overflow
        )
        
        compiled = mjml_to_html(mjml_src)
        html_compiled = compiled.html
        email_content(html_compiled, "RockStocks Daily Update")
        
    except Exception as e:
        logger.error(f"Error occurred during email content compilation: {e}")

    try:
        result = articles.delete_many({})
        logger.info(f"Successfully cleaned {result.deleted_count} collated articles from database")
    except Exception as e:
        logger.error(f"Error cleaning collated articles after email send: {e}")

def reset_daily_announcements() -> None:
    offset = 0
    page_limit = 100
    collected_all = False
    all_items = []
    announcement_collection_id = os.getenv("WEBFLOW_ANNOUNCEMENT_COLLECTION_ID")

    logger.warning("Beginning reset process....")

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
            response.raise_for_status()
            
        except Exception as e:
            logger.error(f"Failure connecting to webflow connection: {e}")

        all_items.extend(response.json()["items"])
        
        if len(response.json()["items"]) < page_limit:
            collected_all = True
        else:
            offset += page_limit
            
    logger.info(f"Found {len(all_items)} announcements to reset.")
            
    if len(all_items) > 0:
        for item in tqdm(all_items, desc="Deleting items"):
           delete_item(os.getenv("WEBFLOW_ANNOUNCEMENT_COLLECTION_ID"), item["id"])
    else:
        logger.warning(f"No announcements found in collection {collection_id} to reset")
           
    logger.info(f"Announcements successfully reset")

def get_hash(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            hash = sha256(f.read()).hexdigest()
        return hash
    except Exception as e:
        logger.error(f"Error hashing file: {e}")
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
        parsed_content = read_pdf(file_path)
        logger.info(f"Successfully parsed content from {file_path}")
        
        summary_prompt = f"Provide a short (maximum 50 word) summary for the following announcement released from company {ticker}. This summary should be attractive and appropriate for a finance blog targeted towards beginner traders. This summary cannot include the ASX ticker in any way, only refer to the company by its' legal name (for example BHP GROUP LIMITED instead of ASX:BHP).\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUMMARY:"
        
        short_title_prompt = f"Suggest an SEO-optimized title for the following company {ticker} announcement appropriate for a finance blog targeted towards beginner traders. This title cannot exceed 60 characters. The title should include critical financial information if needed and summarise all findings and crucial information from the announcement whilst being attractive and enticing to new users. This title cannot include the ASX ticker in any way, only refer to the company by its' legal name (for example BHP GROUP LIMITED instead of ASX:BHP).\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUGGESTED TITLE:"
        
        long_title_prompt = f"Suggest an SEO-optimized title for the following company {ticker} announcement appropriate for a finance blog. The title should include critical financial information if needed and summarise all findings and crucial information from the announcement whilst being attractive and enticing to new users. This title cannot include the ASX ticker in any way, only refer to the company by its' legal name (for example BHP GROUP LIMITED instead of ASX:BHP).\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUGGESTED TITLE:"
        
        email_summary_prompt = f"Provide a short (maximum 40 word) summary for the following announcement released from company {ticker}. This summary should be attractive and appropriate for a email newsletter towards beginner traders. This summary cannot include the ASX ticker OR company name in any way, assume this is already included in the newsletter headline. (for example Announced an initial tungsten resource at its Hillgrove Project instead of Larvotto Resources Limited announced an initial tungsten resource at its Hillgrove Project).\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUMMARY:"
        
        content = await summarize_content(parsed_content, logger, ticker)
        logger.info("Content generated successfully")
        summary = await summarize_content(parsed_content, logger, ticker, prompt=summary_prompt)
        logger.info(f"Summary: {summary}")
        short_title = await summarize_content(parsed_content, logger, ticker, prompt=short_title_prompt)
        logger.info(f"Short title: {short_title}")
        long_title = await summarize_content(parsed_content, logger, ticker, prompt=long_title_prompt)
        logger.info(f"Long title: {long_title}")
        email_summary = await summarize_content(parsed_content, logger, ticker, prompt=email_summary_prompt)
        logger.info(f"Email summary: {email_summary}")
        
        logger.info("Document summarized successfully")
    except Exception as e:
        logger.error(f"Error generating content: {e}")
    
    content =  {
        "short_title": short_title,
        "long_title": long_title,
        "content": content,
        "summary": summary,
        "email_summary": email_summary
    }
    
    return content

def get_stock_data(ticker: str) -> dict:

    entry = all_stocks.get(ticker, None)
    if entry:
        details = entry["fieldData"]
        
        sector = details["company-sector"]
        industry = details["company-industry"]
        industry_group = details["company-industry-group"]
        name = details["company"]
        cap = details["company-market-cap"]
        
        return {
            "sector": sector,
            "industry": industry,
            "industry_group": industry_group,
            "name": name,
            "cap": cap
        }

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
            logger.error(f"Failure in uploading to webflow: {e}")

        all_items.extend(response.json()["items"])
        
        if len(response.json()["items"]) < page_limit:
            collected_all = True
        else:
            offset += page_limit
            
    num_articles = len(all_items)
    return 0 if num_articles is None else num_articles

def push_to_collection(collection_id: str, payload: dict, silent: bool = False) -> None:
    
    success_msg = None
    
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
        
        response.raise_for_status()
        
        response_formatted = response.json()
        message = response_formatted.get("message", None)
        if message:
            logger.critical(f"Failed to push to collection: {collection_id} due to unexpected error: {message}")
        else:
            success_msg = f"Successfully pushed to collection: {collection_id}"
            if not silent:
                logger.info(success_msg)
            
    except Exception as e:
        logger.error(f"Failure in uploading to webflow: {e}")
        
    return success_msg


def search_collection(collection_id: str, search_query: str, field: str = "name", suppress_warning: bool = False) -> str:
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
            response.raise_for_status()
            
        except Exception as e:
            logger.error(f"Failure in uploading to webflow: {e}")

        all_items.extend(response.json()["items"])
        
        if len(response.json()["items"]) < page_limit:
            collected_all = True
        else:
            offset += page_limit
            
    item_id = None
    if len(all_items) > 0:
        for item in all_items:
            if item["fieldData"][field] == search_query:
                return item["id"]
    if suppress_warning is False:   
        logger.warning(f"ERROR: No item found in collection {collection_id} with search term {search_query}") 
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
    except Exception as e:
        logger.warning(f"Failure in fetching image URL from bucket: {e}, using default....")
        
    return url
    
def get_cover_image(industry_id: str) -> str:
    
    industry = all_industries[industry_id]["fieldData"]["name"]
    industry = industry.lower().strip()

    #TODO: Significantly expand this system

    if "oil & gas" in industry:
        bucket = "oilandgas"
    elif "renewable" in industry:
        bucket = "renewables"
    elif "uranium" in industry:
        bucket = "nuclear"
    elif "chemical" in industry:
        bucket = "chemicals"
    elif "coal" in industry:
        bucket = "coal"
    elif "lumber" in industry:
        bucket = "lumber"
    elif "packaging" in industry:
        bucket = "packaging"
    elif "gold" in industry:
        bucket = "gold"
    elif "steel" in industry:
        bucket = "steel"
    elif "agricultur" in industry:
        bucket = "agriculture"
    elif "construction" in industry:
        bucket = "construction"
    elif "biotech" in industry:
        bucket = "biotech"
    elif "logistics" in industry:
        bucket = "logistics"
    elif "silver" in industry:
        bucket = "silver"
    else:
        bucket = "mining"
    
    url = _get_url_from_bucket(bucket)
    
    return url

def _get_stock_id(ticker: str) -> str:
    stock = all_stocks.get(ticker)
    return stock["id"] if stock else None
        
def push_announcement_to_site(hash: str, datetime: str, stock_id: str, formal_title: str, market_sensitive: bool, is_cash_flow: bool, is_substantial: bool) -> None:
    
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
        "announcement-company-2": stock_id,
        "announcement-url": f"https://rtwasxreports.s3.ap-southeast-2.amazonaws.com/{hash}.pdf",
        "market-sensitive": market_sensitive,
        "cash-flow": is_cash_flow,
        "substantial": is_substantial,
        "item-colour": item_colour, # there's probably a way better way of doing this, but it works so I'm keeping it for now
        
    }
    
    announcement_collection_id = os.getenv("WEBFLOW_ANNOUNCEMENT_COLLECTION_ID")
    push_to_collection(announcement_collection_id, fieldData, silent = True)

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
            response.raise_for_status()
    except Exception as e:
        logger.error(f"Failure in dropping live item from webflow: {e}")
        
    try:
            response = requests.delete(
            f"https://api.webflow.com/v2/collections/{collection_id}/items/{item_id}",
            headers = {
                "Authorization": "Bearer " + webflow_access_token,
                "Content-Type": "application/json"
            }
        )
            response.raise_for_status()
    except Exception as e:
        logger.error(f"Failure in deleting from webflow: {e}")

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
            response.raise_for_status()
            
        except Exception as e:
            logger.error(f"Failure in uploading to webflow: {e}")

        all_items.extend(response.json()["items"])
        
        if len(response.json()["items"]) < page_limit:
            collected_all = True
        else:
            offset += page_limit
            
    oldest_item_id = all_items[-1]["id"]
    
    delete_item(collection_id, oldest_item_id)
    
'''
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
'''

def _generate_hashtags(text: str) -> str:
    text_components = text.split("and")
    return " ".join([f"#{component.strip().replace(' ', '')}" for component in text_components])
    
async def push_to_twitter(
    title: str,
    url: str,
    ticker: str,
    industry: str,
    industry_group: str,
    exchange: str = "ASX"
) -> None:
    try:
        if all([title, url, ticker, industry, industry_group]):
            
            hashtags = " ".join([
                f"#{ticker}",
                _generate_hashtags(industry),
                _generate_hashtags(industry_group),
                f"#{exchange}"
            ])
            
            hashes = hashtags.split()
            unique_hashes = set(hashes)
            hashtags = " ".join(unique_hashes)
            
            content = f"{title}\n\n{hashtags}\n\n{url}"

            await twitter_client.create_tweet(text=content)
        else:
            logger.error("Missing content needed for tweet")
    except Exception as e:
        logger.error(f"Unexpected error posting to Twitter: {e}")

def _generate_slug(title: str, max_length: int = 80) -> str:
    title_formatted = title.strip()
    title_formatted = unidecode(title_formatted)
    title_formatted = re.sub(r"\s+", " ", title_formatted)
    slug = re.sub(r"[^a-z0-9]+", "-", title_formatted.lower()).strip("-")
    
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]
        
    return slug

def _convert_to_units(metal: str, price: float, unit: str) -> tuple[float, str]:
    '''Converts metal prices to oz or lb depending on the metal type, based on popular tabular data formats'''
    if metal in ["Gold", "Palladium", "Platinum", "Silver"]:
        if unit == "toz":
            return price / 1.09714, "oz"
        else:
            return price, "oz"
    elif metal in ["Iron"]:
        if unit == "oz":
            return price * 35273.96, "mt"
        return price * 31.1034768
    else: # base case: convert to / lb
        if unit == "toz":
            return price * 14.5833, "lb"
        elif unit == "oz":
            return price * 16, "lb"
        else:
            return price, "lb"

def summarize_alerts() -> None:
    global num_sensitive
    alert_list = list(alerts.find({}))
    metal_list = list(metals.find({}))

    legal_metals = [
        "Aluminium",
        "Copper",
        "Gold",
        "Iron",
        "Lithium"
        "Magnesium",
        "Molybdenum",
        "Nickel",
        "Palladium",
        "Platinum",
        "Silver",
        "Uranium",
        "Zinc"
    ]
    
    screened_metals = []

    for metal in metal_list:
        if metal["name"] in legal_metals:
            metal["price"], metal["unit"] = _convert_to_units(metal["name"], metal["price"], metal["unit"])
            metal["price"] = round(metal["price"], 2)
            screened_metals.append(metal)
        
    
    try:
        mjml_src = announcement_alert_summary_template.render(
            alerts = alert_list,
            metals = screened_metals,
            num_alerts = len(alert_list),
            num_sensitive = num_sensitive,
        )
        
        compiled = mjml_to_html(mjml_src)
        html_compiled = compiled.html
        email_content(html_compiled, f"⚒Alert Update⚒")
        
        return html_compiled
        
    except Exception as e:
        logger.error(f"Error occurred during alert summary compilation: {e}")
    finally:
        alerts.delete_many({})
        num_sensitive = 0

def add_to_email(article_title: str, article_summary: str, article_image: str, article_datetime: str, url: str) -> None:
    
    try:
        formatted_datetime = parse(article_datetime)
    except Exception as e:
        logger.error(f"Error parsing article datetime: {e}")
        return
    
    try:
        articles.insert_one({
            "title": article_title,
            "summary": article_summary,
            "image": article_image,
            "datetime": formatted_datetime,
            "url": url
        })
    except Exception as e:
        logger.error(f"Error adding article to email database: {e}")
        
def _format_assay(drill_metrics: dict) -> str:
    formatted_assay = ""
    formatted_assay += f"{drill_metrics['drill_width_standardized']} m @ "

    formatted_assay += drill_metrics["raw_materials"]
    formatted_assay += f" from {drill_metrics['drill_depth_standardized']} m"
    logger.info(formatted_assay)
    return formatted_assay

def _is_significant(drill_score: float, market_cap: float) -> bool:
    significant = False

    if drill_score >= 200: # high yield
        significant = True
    elif drill_score >= 10 and market_cap <= 1e7: # low yield BUT low market cap (< 10M)
        significant = True
    elif drill_score >= 50 and market_cap >= 1e8: # medium yield and high market cap (>100M)
        significant = True
    
    return significant
        
async def format_alert(file_path: str, ticker: str, report_type: str, article_meta: dict, market_cap: float) -> str:
    results = await get_drill_result(file_path, ticker)
    
    logger.info(report_type)
    
    if results:
        
        market_cap_formatted = _format_market_cap(market_cap)
        #keywords = ["first", "maiden", "explor"]
        
        if _is_significant(results["drill_score"], market_cap):
            results["drill_score"] = int(results["drill_score"])
            assay = _format_assay(results["drill_metrics"])
            
            try:
                mjml_src = announcement_alert_template.render(
                    alert_meta = results,
                    assay = assay,
                    market_cap = market_cap_formatted,
                    report_type = report_type,
                    article_meta = article_meta,
                )
                
                compiled = mjml_to_html(mjml_src)
                html_compiled = compiled.html
                email_content(html_compiled, f"⚒ALERT: ({ticker}) {results['drill_results']['title']}⚒")
                
                alerts.insert_one({
                    "ticker": ticker,
                    "market_cap": market_cap_formatted,
                    "assay": assay,
                    "article_title": article_meta["title"],
                    "article_url": article_meta["url"],
                    "document_title": article_meta["document_title"],
                    "document_url": article_meta["document"],
                    "materials": results["drill_materials"],
                })
                
                article_id = search_collection(os.getenv("WEBFLOW_ARTICLE_COLLECTION_ID"), article_meta["title"], suppress_warning=False)
                if article_id:
                    
                    fieldData = {
                        "name": results["drill_results"]["title"],
                        "result-company": article_meta["company_id"],
                        "result-datetime": article_meta["formatted_datetime"],
                        "assay": assay,
                        "result-article": article_id,
                        "result-document": article_meta["document"],
                    }
                    
                    push_to_collection(os.getenv("WEBFLOW_DRILL_RESULTS_COLLECTION_ID"), fieldData, silent = True)
                
                return html_compiled
                
            except Exception as e:
                logger.error(f"Error occurred during email content compilation: {e}")
        else:
            logger.warning("Drill result failed all three significance benchmarks, skipping alert...")
    else:
        logger.error("Received poorly formatted drill result, skipping alert....")

async def push_article_to_site(file_path: str, announcement_hash: str, formatted_datetime: str, ticker: str, formal_title: str, max_articles: int = 6000, max_attempts: int = 7) -> None:
    collection_id = os.getenv("WEBFLOW_ARTICLE_COLLECTION_ID")
    
    logger.info(f"Beginning construction process for {file_path} {formal_title}....")
    
    try:
        # Check if the article already exists in the site
        article_id = search_collection(collection_id, announcement_hash, "hash-value", suppress_warning=True)
        if article_id:
            logger.warning(f"Attempted publication failed due to pre-existing article on website, skipping....")
            return
        
        num_articles = _get_collection_size(collection_id)
        if num_articles is not None and num_articles > max_articles:
            logger.warning(f"Max article threshold reached, deleting oldest article to make room....")
            drop_oldest(collection_id)
            
        stock_data = get_stock_data(ticker)
        
        if stock_data:

            '''
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
            '''
            
            generated = await generate_content(file_path, ticker)
            
            sector_id = stock_data["sector"]
            industry_id = stock_data["industry"]
            industry_group_id = stock_data["industry_group"]
            ticker_id = search_collection(os.getenv("WEBFLOW_STOCK_COLLECTION_ID"), "ASX:" + ticker)
            cover_image = get_cover_image(stock_data["industry"])
            
            article_slug = _generate_slug(generated["short_title"])
            article_url = f"https://www.rockstocks.ai/articles/{article_slug}"
            
            attempt = 1
            base_delay = 1
            message = None
            
            while attempt <= max_attempts and not message:
                
                logger.info(f"Attempting webflow upload... {attempt} / {max_attempts}")

                if generated:
                    fieldData = {
                        "name": generated["short_title"],
                        "slug": article_slug,
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
                    message = push_to_collection(collection_id, fieldData)
                    
                if not message:
                    if attempt < max_attempts:  # Don't sleep on the last attempt
                        delay = base_delay * (2 ** (attempt - 1))  # Exponential backoff formula
                        delay = min(delay, 60)  # Cap at 60 seconds maximum delay
                        logger.warning(f"Upload failed, waiting {delay} seconds before retry...")
                        await asyncio.sleep(delay)
                    attempt += 1
                        
            if message:
                logger.info("Successfully uploaded article to webflow!")
                industry_name = all_industries[industry_id]["fieldData"]["name"]
                industry_group_name = all_industry_groups[industry_group_id]["fieldData"]["name"]
                
                announcement_type = await get_announcement_type(file_path, ticker)
                if announcement_type.strip() != "N/A":
                    
                    article_meta = {
                        "title": generated["short_title"],
                        "document_title": formal_title,
                        "url": article_url,
                        "document": f"https://rtwasxreports.s3.ap-southeast-2.amazonaws.com/{announcement_hash}.pdf",
                        "ticker": ticker,
                        "company": stock_data["name"],
                        "company_id": ticker_id,
                        "image": cover_image,
                        "summary": generated["email_summary"],
                        "datetime": formatted_datetime
                    }
                
                    await format_alert(file_path, ticker, announcement_type, article_meta, stock_data["cap"])
                else:
                    logger.warning("Received poorly formatted drill result, skipping alert....")
                
                if industry_group_name == "Metals and Mining":
                    industry_group_name = "Mining"
                    
                add_to_email(generated["short_title"], generated["email_summary"], cover_image, formatted_datetime, article_url)
                await push_to_twitter(generated["short_title"], article_url, ticker, industry_name, industry_group_name)
            
            else:
                logger.error("Failed to generate content for article, skipping....")
        else:
            logger.error("Malformed data received, skipping....")
    except Exception as e:
        logger.error(f"Failure in generating article for {file_path} {formal_title}: {e}")    
    finally:
        _remove_file(file_path)    
        logger.info(f"Concluded construction process for {file_path} {formal_title}....")
        
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
        logger.error(f"Error parsing datetime string: {e}")
        
async def announcement_task_wrapper(announcement: dict, progress_bar: tqdm) -> None:
    try:
        async with announcement_semaphore:
            await process_announcement(announcement)
    except Exception as e:
        logger.error(f"Failure in processing announcement {announcement.get('fileId', 'NA')}: {e}")
    finally:
        progress_bar.update(1)
        
def _remove_file(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)

async def download_document(
    client,
    url: str,
    f_name: str,
    headers: dict,
    auth: tuple,
    max_retries: int = 3,
    default_timeout_secs: int = 30,
    timeout_per_mb: int = 1,
    timeout_cap_secs: int = 60,
):
    for attempt in range(1, max_retries + 1):
        try:
            # First, send a HEAD request to get content length
            head_response = await client.head(url, headers=headers, auth=auth)
            content_length = head_response.headers.get("Content-Length")

            # Calculate timeout based on content length (in MB)
            timeout_secs = default_timeout_secs
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                # Add 10 seconds buffer and cap the timeout
                timeout_secs = min(int(size_mb * timeout_per_mb) + 10, timeout_cap_secs)

            logger.debug(f"Attempt {attempt}: Using timeout {timeout_secs}s to download {url}")

            async with async_timeout.timeout(timeout_secs):
                async with client.stream("GET", url, headers=headers, auth=auth) as response:
                    response.raise_for_status()
                    with open(f_name, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
            return True  # success, exit function

        except (httpx.RequestError, httpx.HTTPStatusError, httpx.TimeoutException) as e:
            logger.warning(f"Attempt {attempt} failed to download {url}: {e}")
            if attempt == max_retries:
                logger.error(f"Max retries exceeded for {url}, skipping download.")
                return False
            await asyncio.sleep(2 * attempt)  # exponential backoff

        except asyncio.CancelledError as ce:
            logger.error(f"Download cancelled for {url} on attempt {attempt}: {ce}")
            return False

        except Exception as e:
            logger.warning(f"Unexpected error on attempt {attempt} for {url}: {e}")
            if attempt == max_retries:
                logger.error(f"Max retries exceeded due to unexpected error for {url}, skipping.")
                return False
            await asyncio.sleep(2 * attempt)
            
def validate_stock(ticker: str) -> str:
    
    stock_id = _get_stock_id(ticker)
    
    if stock_id:
        return stock_id
    else:
        missing_stocks_path = "./data/missing_stocks.json"
        missing_stocks = _get_missing_stocks(missing_stocks_path)
        
        if ticker not in missing_stocks["tickers"]:
            missing_stocks["tickers"].append(ticker)
        
        with open(missing_stocks_path, "w") as f:
            json.dump(missing_stocks, f, indent=4)
            
        return None
                
async def process_announcement(announcement: dict) -> None:
    """
    This function processes an individual announcement concurrently by validating,
    generating article content, and pushing it to Webflow asynchronously.
    """
    
    global num_sensitive
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/pdf,application/x-pdf,*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }
    
    auth = (os.getenv("ASX_API_USERNAME"), os.getenv("ASX_API_PASSWORD"))
     
    file_id = announcement.get("fileId", "")
    document_url = announcement.get("documentURL", "")

    f_name = f"./{file_id}.pdf"

    if file_id != "" and document_url != "":
        
        stock_id = validate_stock(announcement.get("code", ""))
        
        if stock_id:
            try: # check to see if document already exists in the database and is properly formed before downloading from API
                if documents.find_one({"file_id": file_id}) is None:
                    """
                    async with asx_download_semaphore:
                        async with httpx.AsyncClient() as client:
                            success = await download_document(client, announcement["documentURL"], f_name, headers = headers, auth = auth)
                            if not success:
                                _remove_file(f_name)
                                return
                    """
                    
                    response = requests.get(
                        announcement["documentURL"], 
                        headers=headers, 
                        auth=auth
                    )
                    
                    response.raise_for_status()
                
                    with open(f_name, "wb") as f:
                        f.write(response.content)
                                    
                    announcement_hash = get_hash(f_name)
                    
                    try:
                        s3_client.upload_file(f_name, "rtwasxreports", f"{announcement_hash}.pdf", ExtraArgs={"ContentType": "application/pdf"})
                    except Exception as e:
                        logger.error(f"Failed uploading file to S3: {e}")
                        _remove_file(f_name)
                        return
                    
                    # generate formatted datetime for article stamp
                    formatted_datetime = _format_datetime(announcement["dateTime"])
            
                    is_cash_flow = True if (("cash" in announcement["heading"].lower()) or ("cashflow" in announcement["heading"].lower())) else False
                    is_substantial = True if "substantial" in announcement["heading"].lower() else False
                        
                    push_announcement_to_site(announcement_hash, formatted_datetime, stock_id, announcement["heading"], announcement["isSensitive"] == "Y", is_cash_flow, is_substantial)

                    #TODO: Improve filtering mechanism to avoid unnecessary uploads
                    if announcement.get("isSensitive", "N") == "Y":
                        num_sensitive += 1
                        if announcement.get("code", "") in legal_tickers and "11001" in announcement.get("newsTypes", []):
                            logger.info("Discovered legal entry!")                                 
                            asyncio.create_task(
                                push_article_to_site(
                                    f_name, announcement_hash, formatted_datetime, announcement["code"], announcement["heading"] # create new process for article generation to ensure announcements are kept up-to-date
                                )
                            )
                        else:
                            _remove_file(f_name)
                    else:
                        _remove_file(f_name)
                
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
                    logger.warning(f"Announcement {announcement['fileId']} already exists in database, skipping download process.")                               
            except Exception as e:
                logger.error(f"Error validating announcement {announcement.get('fileId', 'N/A')}: {e}")
                _remove_file(f_name)     
        else:
            logger.warning(f"Announcement {announcement['fileId']} references missing stock code, skipping download process.")      
    else:
        logger.error(f"Skipping announcement {announcement.get('fileId', 'N/A')} due to malformed content and / or missing document URL.")
        
                   
async def renew_announcements() -> None:

    username = os.getenv("ASX_API_USERNAME")
    password = os.getenv("ASX_API_PASSWORD")
        
    try:
        daily_announcements = requests.get(
            "https://quoteapi.com/files/rtw/asx_news_today.json", 
            auth=(username, password)
        )
        daily_announcements.raise_for_status()
        
        daily_announcements = list(daily_announcements.json())
        last_announcement = daily_announcements[0]
        if documents.find_one({"file_id": last_announcement["fileId"]}):
            logger.info(f"No new announcements found since last poll, skipping....")
        else:
            logger.info(f"New announcements found, processing....")
            
            progress_bar = tqdm(total=len(daily_announcements), desc="Processing announcements")
            
            announcement_processing_tasks = []
            for instance in daily_announcements:
                if instance.get("heading", "end of day").lower() != "end of day":
                    announcement_processing_tasks.append(announcement_task_wrapper(instance, progress_bar))
            
            await tqdm_asyncio.gather(*announcement_processing_tasks)
            
            missing_stocks = _get_missing_stocks()
            missing_stocks = missing_stocks["tickers"]
            logger.critical(f"During announcement processing, the following {len(missing_stocks)} tickers were referenced that do not exist. Suggest adding them to the environment: {sorted(missing_stocks)}")
            
    except Exception as e:
        logger.error(f"Unexpected error encountered when polling ASX announcements: {e}")
                
def _standardize_measurement(measurement: list, unit: str) -> float:
    
    if len(measurement) == 1:
        try:
            measurement = float(measurement[0])
        except (ValueError, TypeError) as e:
            logger.error(f"Error converting measurement {measurement} to float: {e}")
            return None
    else:
        try: # assume a ["lower", "-", "higher"] structure
            measurement_lower = float(measurement[0])
            measurement_upper = float(measurement[2])
            measurement = round((measurement_lower + measurement_upper) / 2, 2)
        except (ValueError, TypeError, IndexError) as e:
            logger.error(f"Error converting measurement {measurement} to float: {e}")
            return None

    if unit == "ft":
        return measurement * 0.3048
    elif unit == "%":
        return measurement * 10000
    elif unit in ["m", "g/t"]:
        return measurement
    else:
        logger.warning(f"Received measurement with unknown unit {unit}, defaulting to metric")
        return measurement
    
def calc_drill_modifier(gxm: float, depth: float, gxm_threshold: float = 10.0, gxm_coeff: float = 0.5, depth_threshold: float = 500.0) -> float:
    depth_modifier = 1 / (1 + math.exp((depth - depth_threshold) / 100))

    if gxm < gxm_threshold:
        gxm_penalty = (gxm / gxm_threshold) ** 3 # penalize extremely small gxm discoveries
    else:
        gxm_penalty = 1
        
    gxm_reward = math.log1p(gxm) * gxm_coeff # ensure gxm doesn't overwhelm depth
    

    modifier = depth_modifier * (gxm_reward * gxm_penalty)

    return modifier

def plot_drill_modifier_heatmap():

    # Create grid of depth and gxm values
    depths = np.linspace(0, 500)     # Depths from 0 to 200 meters
    gxms = np.linspace(0, 300)       # gxm from 0 to 100

    # Compute modifier for each (gxm, depth) pair
    modifier_grid = np.zeros((len(gxms), len(depths)))

    for i, gxm in enumerate(gxms):
        for j, depth in enumerate(depths):
            modifier_grid[i, j] = calc_drill_modifier(gxm, depth)

    # Plot
    plt.figure(figsize=(10, 6))
    cp = plt.contourf(depths, gxms, modifier_grid, levels=200, cmap='viridis')
    plt.colorbar(cp, label='Modifier')
    plt.xlabel('Drill Depth (m)')
    plt.ylabel('AuEq gxm')
    plt.title('Drill Modifier Heatmap')
    plt.savefig("drill_modifier_heatmap.png", dpi=300, bbox_inches="tight")
    plt.show()
    
def get_assay_metrics(result: str) -> dict:
    
    metrics = {
        "drill_width_standardized": None,
        "raw_materials": None,
        "standardized_materials": None,
        "drill_depth_standardized": 0.0
    }
    
    result_components = result.split("$$")
    assay = result_components[0].strip() # ensure that only the assay is used in case of additional generation / hallucination
    
    assay_components = assay.split(";")
    if assay_components[-1] == "":
        assay_components = assay_components[:-1]
    if len(assay_components) == 3:
        drill_width = assay_components[0]
        
        drill_width_components = drill_width.split(" ")
        if len(drill_width_components) > 1:    
            metrics["drill_width_standardized"] = _standardize_measurement(drill_width_components[:-1], drill_width_components[-1].strip())
        else:
            logger.warning("Received assay with missing unit, defaulting to metric")
            metrics["drill_width_standardized"] = _standardize_measurement(drill_width_components[0].strip(), "m")
            if metrics["drill_width_standardized"] == None:
                return None
        
        metrics["raw_materials"] = assay_components[1].strip().replace("[", "").replace("]", "")   
        materials = metrics["raw_materials"].split(",")
        metrics["standardized_materials"] = {}
        for material in materials:
            material_components = material.strip().split(" ")
            material_name = material_components[0].replace(":", "").strip()
            if len(material_name.split(" ")) == 1:
                material_name = material_components[0].replace(":", "").strip()
                metrics["standardized_materials"][material_name] = _standardize_measurement(material_components[1:-1], material_components[-1].strip())
                if metrics["standardized_materials"][material_name] == None:
                    return None
            else:
                return None
                
        drill_depth = assay_components[2].strip()
        drill_depth_components = drill_depth.split(" ")
        metrics["drill_depth_standardized"] = _standardize_measurement(drill_depth_components[:-1], drill_depth_components[-1].strip())
        if metrics["drill_depth_standardized"] == None:
            if drill_depth.lower() in ["eoh", "aircore", "surface", "surface drilling only"]:
                metrics["drill_depth_standardized"] = drill_depth.lower()
            else:
                logger.warning("Received assay with no valid drill depth descriptor, defaulting to surface")
                drill_depth = 0.0
                
    return metrics

def _format_market_cap(market_cap: int):
    if market_cap >= 1e9:
        return f"{round(market_cap / 1e9, 2)}B"
    elif market_cap >= 1e6:
        return f"{round(market_cap / 1e6, 2)}M"
    elif market_cap >= 1e3:
        return f"{round(market_cap / 1e3, 2)}K"
    else:
        return f"{market_cap}"
    
def get_drill_score(assay_metrics: dict) -> dict:
    
    drill_score = {
        "score": 0.0,
        "materials": []
    }
    if assay_metrics["drill_width_standardized"] and assay_metrics["standardized_materials"] and assay_metrics["drill_depth_standardized"]:
        drill_width_standardized = assay_metrics["drill_width_standardized"]
        standardized_materials = assay_metrics["standardized_materials"]
        drill_depth_standardized = assay_metrics["drill_depth_standardized"]        

        gold_doc = metals.find_one({"name": "Gold"})
        gold_price = gold_doc["adjusted_price"] if gold_doc else 0

        material_values = []

        for material, value in standardized_materials.items():
            metal_doc = metals.find_one({"name": material})
            if metal_doc and "adjusted_price" in metal_doc:
                drill_score["materials"].append(material)
                material_value = round(metal_doc["adjusted_price"] * value, 4)
            else:
                logger.warning(f"Received assay with unknown material {material}, defaulting to gold")
                material_value = round(gold_price * value, 4)

            material_values.append(material_value)
            
        total_value = round(sum(material_values), 4)
        gold_equivalent = round(total_value / gold_price, 4)
        gxm = gold_equivalent * drill_width_standardized
        #drill_score = gxm * calc_drill_modifier(gxm, drill_depth_standardized)
        drill_score["score"] = gxm #TODO: Eventually work in modifier once client is happy
    else:
        logger.warning("Received incomplete assay format, skipping....")
    
    return drill_score

async def get_announcement_type(path: str, ticker: str) -> str:
    
    announcement_type = "N/A"
    
    content = read_pdf(path)
    system_prompt = f"You are a highly intelligent AI model trained to classify company drilling reports."
    prompt = f"The following is a drilling report from company with ASX ticker: {ticker} published recently. Please classify the document into the type of drilling report. Format the report type as simply as possible, for example First Pass Drilling instead of First Pass Drilling Report (JORC-compliant). If the report cannot be classified only reply with 'N/A'. Only provide the classification with no justification or additional text.\n\nDOCUMENT: {content}"
    announcement_type = await summarize_content(content, logger, ticker, system_prompt = system_prompt, prompt = prompt)
    return announcement_type

def format_assay_hole_list(assays: str, max_assays: int = 5) -> str:
    
    assay_list = assays.split("\n")
    holes = {}
    formatted_hole_list = ""
    
    for assay in assay_list[:max_assays + 1]:
        assay_components = assay.strip().split("|")
        if len(assay_components) == 2:
            results = f"<li>{assay_components[0].strip()}</li>"
            hole_id = assay_components[1].strip()
             
            if hole_id not in holes:
                holes[hole_id] = results
            else:
                holes[hole_id] += results
           
    for key, value in holes.items(): 
        formatted_hole_list += f"<b>{key}</b>{value}"
       
    formatted_hole_list = formatted_hole_list.replace("<b>N/A</b>", "<b>Untagged</b>") # LLM MOST LIKELY aligned to returning 'N/A' for exceptions / erraneous output, so easier to just fix in the post-format stage rather than relying on the LLM to do it
            
    return formatted_hole_list 

async def get_drill_result(path: str, ticker: str, max_attempts: int = 5) -> dict:
    results = {
        "drill_metrics": None,
        "drill_materials": [],
        "drill_score": 0.0,
        "drill_results": None
    }
    
    attempt = 1
    
    content = read_pdf(path, 1)
    
    system_prompt = f"You are a highly intelligent AI model trained to extract significant drill result assays from company announcements."
    prompt = f"The following is a report from company with ASX ticker: {ticker} published recently. Please extract the most significant drill result assay. Use full names for materials e.g. Copper instead of Cu. The result should be provided in the following format: DRILL WIDTH UNITS; [MATERIAL: QUANTITY UNITS]; DRILL DEPTH UNITS;. End the assay with a $$ symbol. If no drill depth is provided check for EOH / aircore drilling mentions in the assay, in which case use these, otherwise use N/A. Ensure all results have a whitespace between the measurement and unit, for example 10 m instead of 10m. If a range is provided, format as LOWER - UPPER UNITS (e.g. 10 - 20 m instead of 10m - 20m).\n\nDOCUMENT: {content}"
    
    while attempt <= max_attempts and results["drill_score"] == 0.0:
        logger.info(f"Beginning assay analysis.... (attempt {attempt} / {max_attempts})")
        
        assay = await summarize_content(content, logger, ticker, system_prompt = system_prompt, prompt = prompt)
        logger.info(assay)
        
        results["drill_metrics"] = get_assay_metrics(assay)
        attempt += 1
        if results["drill_metrics"] is not None:
            logger.info("Concluded assay analysis")
            drill_score = get_drill_score(results["drill_metrics"])
            results["drill_score"] = drill_score["score"]
            results["drill_materials"] = drill_score["materials"]
        else:
            logger.error("Unexpected error occured when analyzing drill results, retrying....")
        
    
    if results["drill_score"] > 0.0:

        full_content = read_pdf(path)
        
        results["drill_results"] = {
            "significant_assays": "",
            "technical": "",
            "title": "",
            "quote_name": "Unknown",
            "quote_position": "Unknown",
            "quote_content": "N/A",
            "project_name": "",
            "prospect_name": "",
            "project_region": "",
        }
        
        logger.info(f"Constructing detailed technical summary for {ticker}")
        
        system_prompt = f"You are a highly intelligent AI model trained to extract significant drill result assays from company announcements."
        prompt = f"The following is a report from company with ASX ticker: {ticker} published recently. Please extract the most significant drill assays from this report. Each assay should be formatted as WIDTH @ MATERIALS from ENDING DEPTH | HOLE_ID. Each assay should be separated by a new line. If no measurement for materials is provided, do not include in this list. Use full names for materials in these assays e.g. Copper instead of Cu and format quantities as MATERIAL QUANTITY UNITS. Be sure to include starting depth if provided in the assay, otherwise label as from surface. Use shorthand for units (e.g. m instead of metres) and add a whitespace between the measurement and units (e.g. 198 m instead of 198m or 2.3 % instead of 2.3%). If a range is provided, format as LOWER - UPPER UNITS (e.g. 10 - 20 m instead of 10m - 20m). Order assays from most significant to least significant result. If no HOLE_ID is provided for an assay, set the HOLE_ID to N/A e.g. 2 m @ Gold 0.2 g/t from 159 m | N/A. Do not provide any additional text in the response. If no valid assays can be extracted, return N/A.\n\nDOCUMENT: {full_content}"

        significant_assays = await summarize_content(content, logger, ticker, system_prompt = system_prompt, prompt = prompt)
        if significant_assays == "N/A":
            formatted_assay_list = significant_assays
        else:
            formatted_assay_list = format_assay_hole_list(significant_assays)
            
        results["drill_results"]["significant_assays"] = formatted_assay_list
        
        system_prompt = f"You are a highly intelligent AI model trained to provide detailed technical summaries for company drilling reports."
        prompt = f"The following is a report from company with ASX ticker: {ticker} published recently. Please provide a detailed technical summary for the report. This summary should include the key findings of the report as well as a justification for why the findings are important and significant. Only provide the summary with no reference to the provided content. Do not use bullet points or subheadings, only format as paragraph(s). Do not exceed 100 words.\n\nDOCUMENT: {full_content}"
        
        summarized = await summarize_content(full_content, logger, ticker, system_prompt = system_prompt, prompt = prompt)
        
        results["drill_results"]["technical"] = summarized
        
        '''
        system_prompt = f"You are a highly intelligent AI model trained to provide summaries for company announcements targeted towards investors."
        prompt = f"The following is a report from company with ASX ticker: {ticker} published recently. Please provide a a summary of how these findings could impact the company's valuation on the australian stock exchange. This should be targeted towards a trader / potential investor in the company. The summary should be formatted so that it directly addresses the trader #viewing this summary however it should NEVER mention the trader by name or title (e.g. avoid using 'The Trader' or 'A Trader'). Do not use bullet points or subheadings, only format as #paragraph(s). Do not include assays in this summary. Do not exceed 200 words.\n\nDOCUMENT: {full_content}"
        
        summarized = await summarize_content(full_content, logger, ticker, system_prompt = system_prompt, prompt = prompt)
        results["drill_results"]["investor"] = summarized
        '''
        
        system_prompt = f"You are a highly intelligent AI model trained to provide projections and potential future actions based on company announcements targeted towards investors."
        prompt = f"The following is a report from company with ASX ticker: {ticker} published recently. Based on the findings from this document and the general state of the industry that the company operates in, provide a summary of what future actions the company could take based on the findings in this report, and how this may impact its' future performance and valuation on the australian stock exchange. This should be targeted towards a trader / potential investor in the company with an intermediate to advanced level of experience. The summary should be formatted so that it directly addresses the trader viewing this summary however it should NEVER mention the trader by name or title (e.g. avoid using 'The Trader' or 'A Trader'). Do not use bullet points or subheadings, only format as paragraph(s). Do not include assays in this summary. Do not exceed 100 words.\n\nDOCUMENT: {full_content}"
        
        summarized = await summarize_content(full_content, logger, ticker, system_prompt = system_prompt, prompt = prompt)
        results["drill_results"]["projection"] = summarized
    
        system_prompt = f"You are a highly intelligent AI model trained to provide titles for company announcements."
        prompt = f"The following is an announcement from company with ASX ticker: {ticker} published recently. Please provide a short title for the announcement appropriate for an email alert for a potential investor / trader. This title should be SEO-optimized and include simple language that summarizes the announcement without including technical markers or data points. \n\nANNOUNCEMENT: {full_content}"
        
        
        title = await summarize_content(full_content, logger, ticker, system_prompt = system_prompt, prompt = prompt)
        results["drill_results"]["title"] = title
        
        system_prompt = f"You are a highly intelligent AI model trained to extract project details from drilling reports."
        prompt = f"The following is a report from company with ASX ticker: {ticker} published recently. Please extract the full project name, prospect name and the region the project is being conducted in. The response should be formatted as the following: PROJECT NAME; PROSPECT NAME; REGION. If any of these cannot be provided, replace the relevant field with 'N/A'.\n\nDOCUMENT: {full_content}"
        
        
        project_details = await summarize_content(full_content, logger, ticker, system_prompt = system_prompt, prompt = prompt)
        project_details = project_details.strip().split(";")
        
        if len(project_details) == 3:
            results["drill_results"]["project_name"] = project_details[0]
            results["drill_results"]["prospect_name"] = project_details[1]
            results["drill_results"]["project_region"] = project_details[2]
        else:
            results["drill_results"]["project_name"] = "N/A"
            results["drill_results"]["prospect_name"] = "N/A"
            results["drill_results"]["project_region"] = "N/A"
            
            
        system_prompt = f"You are a highly intelligent AI model trained to extract key quotes from drilling reports."
        prompt = f"The following is a drilling report from company with ASX ticker: {ticker} published recently. Please attempt to extract a relevant quote from a relevant stakeholder. Format this quote as <PERSON> | <POSITION> | <QUOTE>. If no name or person is provided, simply use Unknown. If no relevant quote can be extracted only reply with 'N/A'. Only provide the quote with no justification or additional text. Do not attempt to generate a quote that isn't part of the report or from a relevant stakeholder. If multiple quotes are detected only return the most relevant quote.\n\nDOCUMENT: {full_content}"
        
        detected_quote = await summarize_content(content, logger, ticker, system_prompt = system_prompt, prompt = prompt)
        
        quote_components = detected_quote.strip().split("|")
        
        if len(quote_components) == 3:
            results["drill_results"]["quote_name"] = quote_components[0].strip()
            results["drill_results"]["quote_position"] = quote_components[1].strip()
            results["drill_results"]["quote_content"] = quote_components[2].strip()
        
    else:
        logger.error(f"Could not extract drill assay within maximum allowed attempts, skipping....")
        
    return results

@asynccontextmanager
async def lifespan(app: FastAPI):
    
    logger.info("Starting FastAPI application...")
    
    scheduler = AsyncIOScheduler(
        timezone = "Australia/Sydney"
    )
    
    scheduler.add_job(
        update_metal_prices,
        "cron",
        day_of_week="mon,tue,wed,thu,fri",
        hour="6,14",
        minute=30,
        max_instances=1,
        name="update_metal_prices"
    )
    
    # ASX Announcement polling (trading days only)
    scheduler.add_job(
        renew_announcements,
        "cron",
        day_of_week="mon,tue,wed,thu,fri",
        hour="7-17",
        minute="*",
        max_instances=1,
        name="renew_announcements"
    )
    
    # Daily reset (23:30 on trading days)
    scheduler.add_job(
        reset_daily_announcements,
        "cron",
        day_of_week="mon,tue,wed,thu",
        hour=23,
        minute=30,
        max_instances=1,
        name="reset_announcements"
    )
    
    # Email collection (09:00, 12:00 and 15:00 on trading days)
    scheduler.add_job(
        collect_for_email,
        "cron",
        day_of_week="mon,tue,wed,thu,fri",
        hour="9,12,17",
        minute=0,
        max_instances=1,
        name="email_collection"
    )
    
    # Email alert aggregation
    scheduler.add_job(
        summarize_alerts,
        "cron",
        day_of_week="mon,tue,wed,thu,fri",
        hour="9,15",
        minute=50,
        max_instances=1,
        name="summarize_alerts"
    )
    scheduler.start()
    yield
    
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def read_root():
    return {"message": "Welcome to the FastAPI application"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
