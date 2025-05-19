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
from hashlib import sha256
from logging import getLogger, LogRecord, Formatter, INFO, StreamHandler
from pytz import timezone as tz

import httpx
import uvicorn

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asyncio import Semaphore
import boto3 as b3
from fastapi import FastAPI
from pymongo import MongoClient
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio
from tweepy.asynchronous import AsyncClient
from unidecode import unidecode

from dotenv import load_dotenv
load_dotenv()

reset_executor = ThreadPoolExecutor(max_workers=1)

class CustomAsyncHandler(StreamHandler):
    def __init__(self):
        super().__init__()
        colorama.init()
        self._colors = {
            "INFO": colorama.Fore.GREEN,
            "WARNING": colorama.Fore.YELLOW,
            "ERROR": colorama.Fore.RED,
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
asx_download_semaphore = Semaphore(3)

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

missing_stocks = []

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
        os.getenv("TWITTER_ACCESS_SECRET"),
        wait_on_rate_limit=True
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

all_stocks = cache_collection(os.getenv("WEBFLOW_STOCK_COLLECTION_ID"), "ticker", "./server/data/cached_stocks.json")
all_industries = cache_collection(os.getenv("WEBFLOW_INDUSTRY_COLLECTION_ID"), "id", "./server/data/cached_industries.json")

if all_stocks and all_industries:
    logger.info("Successfully loaded all stocks and industries from cache")

def _get_curr_time():
    return datetime.now(tz("Australia/Sydney"))

'''
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
'''

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
        missing_stocks_path = "./server/data/missing_stocks.json"

        if os.path.exists(missing_stocks_path):
            with open(missing_stocks_path, "r") as f:
                missing_stocks = json.load(f)
        else:
            missing_stocks = {
                "tickers": []
            }
        
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

def collect_for_email(article_title: str, article_summary: str, article_image: str, url: str) -> None:
    articles.insert_one({
        "title": article_title,
        "summary": article_summary,
        "image": article_image,
        "url": url
    })
    
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
                collect_for_email(generated["short_title"], generated["email_summary"], cover_image, article_url)
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
            logger.error(f"Unexpected error on attempt {attempt} for {url}: {e}")
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
    
    legal_tickers = ["29M", "A11", "A1M", "A4N", "AAI", "AAR", "ADT", "AEE", "AEL", "AGE", "AIS", "AKM", "ALD", "ALK", "AMC", "AMI", "ARR", "ARU", "ASL", "ATR", "AUC", "AVL", "AZY", "BC8", "BCI", "BCK", "BCN", "BGL", "BHP", "BIS", "BKW", "BKY", "BMN", "BOC", "BOE", "BPT", "BRE", "BRI", "BRL", "BSL", "BTR", "CAA", "CAY", "CHN", "CIA", "CMM", "COI", "CRD", "CRN", "CSC", "CTM", "CVN", "CVV", "CXO", "CYL", "DEG", "DGL", "DLI", "DRR", "DRX", "DVP", "DYL", "EEG", "EGR", "EMR", "ENR", "EQR", "ERA", "ETM", "EVN", "FEX", "FFM", "FMG", "GG8", "GMD", "GNG", "GOR", "GRR", "GRX", "HCH", "HRZ", "HZN", "IGO", "ILU", "IMA", "IMD", "INR", "IPL", "IPX", "JHX", "JMS", "KAR", "KCN", "KLL", "LCY", "LIN", "LLL", "LOT", "LRV", "LTR", "LYC", "MAC", "MAH", "MAU", "MDX", "MEI", "MEK", "MGX", "MIN", "MLX", "MM8", "MMI", "MRL", "NEM", "NHC", "NIC", "NMG", "NST", "NTU", "NUF", "NXG", "OBM", "OMA", "OMH", "ORA", "ORI", "ORN", "PDI", "PDN", "PEN", "PGH", "PLS", "PMT", "PNR", "POL", "PRG", "PRN", "PRU", "PTN", "PTR", "QGL", "QPM", "RHI", "RIO", "RMS", "RND", "RNU", "RRL", "RSG", "RXL", "S32", "SBM", "SFR", "SGM", "SMI", "SMR", "SPR", "STA", "STK", "STO", "STX", "SVL", "SVM", "SX2", "SYA", "SYR", "TBN", "TBR", "TCG", "TGM", "TLG", "TTM", "TTT", "TVN", "TZN", "USL", "VAU", "VEA", "VSL", "VUL", "VYS", "WA1", "WAF", "WC8", "WDS", "WGN", "WGX", "WHC", "WIA", "YAL", "ZIM"] 
    
    file_id = announcement.get("fileId", "")
    
    if not file_id:
        logger.error(f"Skipping announcement {announcement.get('dateTime', 'N/A')} due to malformed content")
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
            daily_announcements.reverse()
            
            daily_announcements = daily_announcements[:200]
            
            progress_bar = tqdm(total=len(daily_announcements), desc="Processing announcements")
            
            announcement_processing_tasks = []
            for instance in daily_announcements:
                if instance.get("heading", "end of day").lower() != "end of day":
                    announcement_processing_tasks.append(announcement_task_wrapper(instance, progress_bar))
            
            await tqdm_asyncio.gather(*announcement_processing_tasks)
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
        #hour="7-23",
        minute="*",
        max_instances=1
    )
    
    # Daily reset (23:30 on trading days)
    scheduler.add_job(
        lambda: asyncio.get_event_loop().run_in_executor(
            reset_executor, reset_daily_announcements
        ),
        "cron",
        day_of_week="mon,tue,wed,thu",
        hour=23,
        minute=30,
        max_instances=1,
        name="reset_announcements"
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