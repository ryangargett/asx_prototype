import asyncio
import async_timeout
import colorama
import holidays
import json
import os
import pytz
import random
import regex as re
import requests
import traceback

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from dateutil.parser import parse
from hashlib import sha256
from logging import getLogger, LogRecord, Formatter, INFO, StreamHandler
from pytz import timezone as tz

import httpx
import uvicorn

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asyncio import Semaphore
import boto3 as b3
from fastapi import FastAPI
from jinja2 import Environment, FileSystemLoader
from mjml import mjml_to_html
from pymongo import MongoClient
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio
from tweepy.asynchronous import AsyncClient
from unidecode import unidecode

from dotenv import load_dotenv
load_dotenv()

jinja_env = Environment(loader=FileSystemLoader("./data/templates"))
email_template = jinja_env.get_template("email.mjml.j2")

reset_executor = ThreadPoolExecutor(max_workers=1)
email_executor = ThreadPoolExecutor(max_workers=1)

class CustomAsyncHandler(StreamHandler):
    def __init__(self):
        super().__init__()
        colorama.init()
        self._colors = {
            "INFO": colorama.Fore.GREEN,
            "WARNING": colorama.Fore.YELLOW,
            "ERROR": colorama.Fore.RED,
            "CRITICAL": colorama.Fore.MAGENTA
        }
        self._reset = colorama.Style.RESET_ALL

    def get_color(self, levelname: str) -> str:
        return self._colors.get(levelname, '')

    def format(self, record: LogRecord) -> str:
        message = super().format(record)
        return f"{self.get_color(record.levelname)}{message}{self._reset}"

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)
            
logger = getLogger("asx_app_logger")
logger.setLevel(INFO)

handler = CustomAsyncHandler()
formatter = Formatter("%(asctime)s | %(levelname)s | %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

announcement_semaphore = Semaphore(10)
asx_download_semaphore = Semaphore(2)

from summarizer import read_pdf, summarize_content

mongo_client = MongoClient(os.getenv("MONGODB_KEY"))

# Check if cluster is connected
try:
    mongo_client.admin.command('ping')
    logger.info("MongoDB connection successful")
except Exception as e:
    logger.error(f"MongoDB connection failed - {e}")

access_token = os.getenv("WEBFLOW_API_KEY")
collection_id = os.getenv("WEBFLOW_COLLECTION_ID")    

db = mongo_client["main"]
documents = db["documents_new_2"]
stocks = db["stocks"]
articles = db["articles"]

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

if all_stocks and all_industries and all_industry_groups:
    logger.info("Successfully loaded all stocks and industries from cache")
    
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
            
legal_tickers = get_legal_tickers()

if legal_tickers:
    logger.info("Successfully loaded legal tickers from cache")

def _get_curr_time():
    return datetime.now(tz("Australia/Sydney"))

def collect_for_email() -> None:
    logger.info("Starting email collection task.")

    try:
        collated_articles = list(articles.find({}).sort("datetime", -1))
        logger.info(f"Fetched {len(collated_articles)} collated articles from the database.")

        email_list = []
        for article in collated_articles:
            email_list.append(article)
            

        mjml_src = email_template.render(articles=email_list)
        compiled = mjml_to_html(mjml_src)
        html_compiled = compiled.html

        mailgun_key = os.getenv("MAILGUN_KEY")
        if not mailgun_key:
            logger.error("MAILGUN_KEY environment variable is missing. Cannot send email.")
            return
        
        emails = [
            "dev@dunelmenterprises.com.au",
            #"es@eveq.com",
            #"rtwcapitaltrade@gmail.com"
        ]
        
        for email in emails:

            response = requests.post(
                "https://api.mailgun.net/v3/sandboxbc8c028db9ae4488860adcc36c74d11b.mailgun.org/messages",
                auth=("api", mailgun_key),
                data={
                    "from": "Mailgun Sandbox <postmaster@sandboxbc8c028db9ae4488860adcc36c74d11b.mailgun.org>",
                    "to": f"Eric Samuel <{email}>",
                    "subject": "RockStocks Updates",
                    "html": html_compiled
                }
            )
            logger.info(f"Mailgun response status: {response.status_code}")
            
            if response.ok:
                logger.info("Email sent successfully.")
            else:
                logger.error(f"Failed to send email. Response: {response.text}")

    except Exception as e:
        logger.exception(f"Exception occurred during email sending: {e}")

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
        
        summary_prompt = f"Provide a short (maximum 50 word) summary for the following announcement released from company {ticker}. This summary should be attractive and appropriate for a finance blog targeted towards beginner traders. This summary cannot include the ASX ticker in any way, only refer to the company by its' legal name (for example BHP GROUP LIMITED instead of ASX:BHP).\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUMMARY:"
        
        short_title_prompt = f"Suggest an SEO-optimized title for the following company {ticker} announcement appropriate for a finance blog targeted towards beginner traders. This title cannot exceed 60 characters. The title should include critical financial information if needed and summarise all findings and crucial information from the announcement whilst being attractive and enticing to new users. This title cannot include the ASX ticker in any way, only refer to the company by its' legal name (for example BHP GROUP LIMITED instead of ASX:BHP).\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUGGESTED TITLE:"
        
        long_title_prompt = f"Suggest an SEO-optimized title for the following company {ticker} announcement appropriate for a finance blog. The title should include critical financial information if needed and summarise all findings and crucial information from the announcement whilst being attractive and enticing to new users. This title cannot include the ASX ticker in any way, only refer to the company by its' legal name (for example BHP GROUP LIMITED instead of ASX:BHP).\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUGGESTED TITLE:"
        
        email_summary_prompt = f"Provide a short (maximum 40 word) summary for the following announcement released from company {ticker}. This summary should be attractive and appropriate for a email newsletter towards beginner traders. This summary cannot include the ASX ticker OR company name in any way, assume this is already included in the newsletter headline. (for example Announced an initial tungsten resource at its Hillgrove Project instead of Larvotto Resources Limited announced an initial tungsten resource at its Hillgrove Project).\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUMMARY:"
        
        content = await summarize_content(parsed_content, logger, ticker)
        summary = await summarize_content(parsed_content, logger, ticker, prompt=summary_prompt)
        short_title = await summarize_content(parsed_content, logger, ticker, prompt=short_title_prompt)
        long_title = await summarize_content(parsed_content, logger, ticker, prompt=long_title_prompt)
        email_summary = await summarize_content(parsed_content, logger, ticker, prompt=email_summary_prompt)
        
        logger.info(f"Summary: {summary}")
        logger.info(f"Short title: {short_title}")
        logger.info(f"Long title: {long_title}")
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
        
        return {
            "sector": sector,
            "industry": industry,
            "industry_group": industry_group
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
            
    except Exception as e:
        logger.error(f"Failure in uploading to webflow: {e}")


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

def _get_missing_stocks(file_path: str = "./data/missing_stocks.json") -> None:
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            missing_stocks = json.load(f)
    else:
        missing_stocks = {
            "tickers": []
        }
        
    return missing_stocks
        
def push_announcement_to_site(hash: str, datetime: str, ticker: str, formal_title: str, market_sensitive: bool, is_cash_flow: bool, is_substantial: bool) -> str:
    
    #TODO: Reimplement once cms collection size cap has been increased, for now just use raw ticker
    
    #ticker_collection_id = os.getenv("WEBFLOW_TICKER_COLLECTION_ID")
    #ticker_id = search_collection(ticker_collection_id, ticker)
    
    if market_sensitive:
        item_colour = "#FFBF00"
    else:
        item_colour = "#FFFFFF"
    
    stock_id = _get_stock_id(ticker)
    
    if stock_id:
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
        push_to_collection(announcement_collection_id, fieldData)
        
        return "success"
    else:
        missing_stocks_path = "./data/missing_stocks.json"
        missing_stocks = _get_missing_stocks(missing_stocks_path)
        
        if ticker not in missing_stocks["tickers"]:
            missing_stocks["tickers"].append(ticker)
        
        with open(missing_stocks_path, "w") as f:
            json.dump(missing_stocks, f, indent=4)
            
        return None

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
        logger.error(f"Failure in dropping live item from webflow: {e}")
        
    try:
            response = requests.delete(
            f"https://api.webflow.com/v2/collections/{collection_id}/items/{item_id}",
            headers = {
                "Authorization": "Bearer " + webflow_access_token,
                "Content-Type": "application/json"
            }
        )
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
    
async def push_to_twitter(title: str, article_url: str) -> None:
    try:
        if title and article_url:  
            if len(title) > 130:
                title = title[:127] + "..."

            await twitter_client.create_tweet(
                text = f"{title}\n\n{article_url}"
            )
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
    
async def push_article_to_site(file_path: str, announcement_hash: str, formatted_datetime: str, ticker: str, formal_title: str, max_articles: int = 6000) -> None:
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
            
            add_to_email(generated["short_title"], generated["email_summary"], cover_image, formatted_datetime, article_url) # moved up priority queue to ensure articles are properly added to the email collection
            
            logger.info("Attempting webflow upload...")

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
                push_to_collection(collection_id, fieldData)
                await push_to_twitter(generated["short_title"], article_url)
            
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
    
    auth = (os.getenv("ASX_API_USERNAME"), os.getenv("ASX_API_PASSWORD"))
     
    file_id = announcement.get("fileId", "")
    document_url = announcement.get("documentURL", "")
    
    if not file_id:
        logger.error(f"Skipping announcement {announcement.get('id', 'N/A')} due to malformed content")
        return
    
    if not document_url:
        logger.warning(f"Skipping announcement {announcement.get('fileId', 'N/A')} due to missing document")
        return

    f_name = f"./{file_id}.pdf"

    try: # check to see if document already exists in the database and is properly formed before downloading from API
        if documents.find_one({"file_id": file_id}) is None:
            async with asx_download_semaphore:
                async with httpx.AsyncClient() as client:
                    success = await download_document(client, announcement["documentURL"], f_name, headers = headers, auth = auth)
                    if not success:
                        _remove_file(f_name)
                        return
                            
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
                
            result = push_announcement_to_site(announcement_hash, formatted_datetime, announcement["code"], announcement["heading"], announcement["isSensitive"] == "Y", is_cash_flow, is_substantial)

            #TODO: Improve filtering mechanism to avoid unnecessary uploads
            if result:
                if announcement.get("isSensitive", "N") == "Y" and announcement.get("code", "") in legal_tickers:
                    logger.info("Discovered legal entry!")                                 
                    asyncio.create_task(
                        push_article_to_site(
                            f_name, announcement_hash, formatted_datetime, announcement["code"], announcement["heading"] # create new process for article generation to ensure announcements are kept up-to-date
                        )
                    )
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
                logger.warning(f"Announcement {announcement['fileId']} references missing stock code, skipping download process.")
                _remove_file(f_name)
        else:
            logger.warning(f"Announcement {announcement['fileId']} already exists in database, skipping download process.")
            _remove_file(f_name)
            
    except Exception as e:
        logger.error(f"Error validating announcement {announcement.get('fileId', 'N/A')}: {e}")
        #logger.error(traceback.format_exc())
        _remove_file(f_name)
                   
async def renew_announcements() -> None:

    username = os.getenv("ASX_API_USERNAME")
    password = os.getenv("ASX_API_PASSWORD")
        
    try:
        daily_announcements = requests.get(
            "https://quoteapi.com/files/rtw/asx_news_today.json", 
            auth=(username, password)
        )
        
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
            logger.critical(f"During announcement processing, the following {len(missing_stocks)} tickers were referenced that do not exist. Suggest adding them to the environment: {missing_stocks}")
            
    except Exception as e:
        logger.error(f"Unexpected error encountered when polling ASX announcements: {e}")
        
        curr_time = _get_curr_time()
        
        if curr_time.weekday() < 4: # Monday to Thursday, we keep announcements over the weekend
            if curr_time.hour >= 23 and curr_time.minute >= 30:
                logger.warning(f"End of trading day, resetting announcements....")
                reset_daily_announcements()

@asynccontextmanager
async def lifespan(app: FastAPI):
    
    logger.info("Starting FastAPI application...")
    
    scheduler = AsyncIOScheduler(
        timezone = "Australia/Sydney"
    )
    
    # ASX Announcement polling (trading days only)
    scheduler.add_job(
        renew_announcements,
        "cron",
        day_of_week="mon,tue,wed,thu,fri",
        hour="7-17",
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
    
    scheduler.start()
    yield
    
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def read_root():
    return {"message": "Welcome to the FastAPI application"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
