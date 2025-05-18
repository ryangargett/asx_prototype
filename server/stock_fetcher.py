import os
import json
import requests


import pandas as pd
import regex as re

from pymongo import MongoClient
from scraperapi_sdk import ScraperAPIClient
from collections import Counter
from tqdm import tqdm

from app import search_collection

mongo_client = MongoClient(os.getenv("MONGODB_KEY"))
collection_id = os.getenv("WEBFLOW_STOCK_COLLECTION_ID")
access_token = os.getenv("WEBFLOW_API_KEY")

# Check if cluster is connected
try:
    mongo_client.admin.command('ping')
    print("MongoDB connection: Successful")
except Exception as e:
    print(f"MongoDB connection: Failed - {e}")
    
db = mongo_client["main"]
stocks = db["stocks_new"]
stock_backup = db["stocks_backup"]

#stocks.delete_many({}) # delete all stocks in the collection to ensure no duplicates are present
    
scraper_client = ScraperAPIClient("ef892f62cf4c6c90385d2b5ef59281fe")
'''
def lookup_valid_material_subsector(sector: str, subsector: str, desc: str) -> str:
    
    valid_materials = ["copper", "gold", "silver", "iron", "aluminium", "zinc", "nickel", "cobalt", "lithium", "uranium", "platinum", "oil", "mineral sands", "rare earth", "hydrogen", "graphite", "gas", "lead", "palladium", "potash", "tin", "vanadium"]
    
    if "material" in sector.lower():
        for material in valid_materials:
            if material in subsector.lower():
                return subsector.lower()
            
        diversified_materials = []
            
        for material in valid_materials:
            if material in desc.lower():
                diversified_materials.append(material)
        
        if len(diversified_materials) > 0:      
            return ", ".join(diversified_materials)
    
    else:
        return subsector

def get_asx_tickers():
    """
    Fetches the list of ASX-listed companies and returns a list of tickers.
    """
    url = "https://www.asx.com.au/asx/research/ASXListedCompanies.csv"
    response = requests.get(url)
    if response.status_code == 200:
        # Read the CSV content into a DataFrame
        df = pd.read_csv(io.StringIO(response.text), skiprows=1)
        # Extract the tickers
        tickers = df["ASX code"].tolist()
        return tickers
    else:
        raise Exception("Failed to fetch ASX-listed companies.")
    
def get_company_info(ticker: str) -> dict:
    """
    Fetches company details (name, sector, subsector, company summary) using yfinance. Skips any companies that do not have a sector to ensure only valid companies are incorporated.
    """
    try:
        stock = yf.Ticker(ticker + ".AX")  # Ensure that the correct exchange is specified, potentially add support outside of aus in the future?
        info = stock.info
        
        long_name = info.get("longName", "N/A")
        sector = info.get("sector", "N/A")
        subsector = info.get("industry", "N/A")
        summary = info.get("longBusinessSummary", "N/A")
        market_cap = info.get("marketCap", "N/A")
        share_revenue = info.get("revenuePerShare", "N/A")
        share_book = info.get("bookValue", "N/A")
        share_div = info.get("dividendRate", "N/A")
        volume = info.get("averageVolume", "N/A")
        
        valid_sectors = ["materials", "energy"]
        
        
        if sector.lower() in valid_sectors:
            return {
                "ticker": ticker,
                "company_name": long_name,
                "sector": sector,
                "subsector": lookup_valid_material_subsector(sector, subsector, summary),
                "summary": summary,
                "market_cap": market_cap,
                "share_revenue": share_revenue,
                "share_book": share_book,
                "share_div": share_div,
                "volume": volume
            }
        else:
            return None
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return None
'''

def get_company_info(ticker):
    headers = {
        "accept": "*/*",
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Accept-Language" : "en-US,en;q=0.9",
        "referer": "https://au.finance.yahoo.com/",
        "cookie": "GUC=AQEBCAFn42toC0IfQASM&s=AQAAAJmX2cB-&g=Z-IiRA; A1=d=AQABBNCHQGcCEFM4R265BmtvGc7pW9YLLEwFEgEBCAFr42cLaA0CxyMA_eMBAAcI0IdAZ9YLLEw&S=AQAAAsDj1lFDSpaDKmRVAeHcM4I; A3=d=AQABBNCHQGcCEFM4R265BmtvGc7pW9YLLEwFEgEBCAFr42cLaA0CxyMA_eMBAAcI0IdAZ9YLLEw&S=AQAAAsDj1lFDSpaDKmRVAeHcM4I; A1S=d=AQABBNCHQGcCEFM4R265BmtvGc7pW9YLLEwFEgEBCAFr42cLaA0CxyMA_eMBAAcI0IdAZ9YLLEw&S=AQAAAsDj1lFDSpaDKmRVAeHcM4I; PRF=t%3DBHP.AX%252B29M.AX%252BNST.AX"
    }
    
    try:
        response = scraper_client.get(url=f"https://finance.yahoo.com/quote/{ticker}?p={ticker}",
                                  headers=headers)
    except Exception as e:
        print(f"Failed to fetch data for {ticker}: {e}")
        return None

    info_pattern = r'longBusinessSummary\\":\\\"(.*?)\\\"'
    industry_pattern = r'\\\"industry\\\":\\\"(.*?)\\\"'

    info_match = re.search(info_pattern, response)
    if info_match:
        summary = info_match.group(1)
        tqdm.write(f"\n{summary}")
    else:
        tqdm.write(f"\nNo valid summary")
        
    industry_match = re.search(industry_pattern, response)
    if industry_match:
        industry = industry_match.group(1)
        tqdm.write(f"\n{industry}")
    else:
        tqdm.write(f"\nNo valid industry")

    if not info_match or not industry_match:
        return None
    else:
        return {
            "ticker": ticker,
            "summary": summary,
            "industry": industry
        }
        
def _format_ticker(ticker: str) -> str:
    ticker_components = ticker.strip().split(":")
    formatted_ticker = ticker_components[1].strip() + ".AX"
    return formatted_ticker

def _format_company_name(name: str) -> str:
    name_components = name.strip().split("(")
    return(name_components[0].strip())
    
def format_company_listing(file_path: str) -> pd.DataFrame:
    
    company_data = pd.read_csv(
        file_path, 
        header = 0,
        names = ["ticker", "name", "website", "cap", "last trade", "change", "change %", "sector"]
    )
    
    print(company_data.head())
    
    company_data["ticker"] = company_data["ticker"].apply(_format_ticker)
    company_data["name"] = company_data["name"].apply(_format_company_name)
    company_data = company_data[company_data["sector"].str.lower() != "unclassified"] # drop any ETFs or otherwise unclassified companies
    company_data.sort_values(by = "ticker", inplace = True)
    
    #valid_sectors = ["materials", "energy"]
    #filtered_data = full_data[full_data["sector"].str.lower().isin(valid_sectors)]
    
    company_data.to_csv("./server/data/asx_companies.csv")
    return company_data
    
def get_energy_sector_industries():
    """
    Scans the MongoDB collection for all tickers with the 'energy' sector,
    retrieves the unique industries, and tracks the count of companies under each industry.
    """
    try:
        # Query the MongoDB collection for documents with sector 'energy'
        energy_companies = stocks.find({"sector": "Energy"})
        
        # Extract industries and count occurrences
        industry_counter = Counter()
        for company in energy_companies:
            industry = company.get("industry", "NA")
            industry_counter[industry] += 1
        
        # Convert Counter to a dictionary
        industry_dict = dict(sorted(industry_counter.items(), key=lambda x: x[1], reverse=True))
        
        print("Industry counts for 'energy' sector:")
        for industry, count in industry_dict.items():
            print(f"{industry}: {count}")
    except Exception as e:
        print(f"Error while fetching energy sector industries: {e}")
        
def get_tickers_by_sector_and_industry(sector: str, industry: str) -> list:
    """
    Retrieves a list of all tickers associated with the given sector and industry.
    
    Args:
        sector (str): The sector to filter by.
        industry (str): The industry to filter by.
    
    Returns:
        list: A list of tickers matching the sector and industry.
    """
    try:
        # Query the MongoDB collection for documents matching the sector and industry
        query = {"sector": sector, "industry": industry}
        matching_companies = stocks.find(query, {"ticker": 1, "_id": 0})
        
        # Extract tickers from the query result
        tickers = [company["ticker"] for company in matching_companies]
        tickers.sort()
        
        print(f"Found {len(tickers)} tickers for sector '{sector}' and industry '{industry}':")
        print(tickers)
        
        return tickers
    except Exception as e:
        print(f"Error while fetching tickers for sector '{sector}' and industry '{industry}': {e}")
        return []
    
def lookup_industry_sector(industry_group: str) -> str:
    
    sector = None
    
    if industry_group in ["Consumables", "Renewables"]:
        sector = "Energy"
    elif industry_group in ["Chemicals", "Containers and Packaging", "Metals and Mining", "Paper and Forest Products"]:
        sector = "Materials"
    elif industry_group in ["Capital Goods", "Commercial and Professional Services", "Transportation"]:
        sector = "Industrials"
    elif industry_group in ["Automobiles and Components", "Consumer Durables and Apparel", "Consumer Services", "Consumer Discretionary Distribution and Retail"]:
        sector = "Consumer Discretionary"
    elif industry_group in ["Consumer Staples Distribution and Retail", "Food, Beverage and Tobacco", "Household and Personal Products"]:
        sector = "Consumer Staples"
    elif industry_group == "Healthcare and Pharmaceuticals":
        sector = "Health Care"
    elif industry_group in ["Banks", "Financial Services", "Insurance", "Investment Funds"]:
        sector = "Financials"
    elif industry_group in ["Software and Services", "Technology Hardware and Equipment"]:
        sector = "Information Technology"
    elif industry_group in ["Telecommunication Services", "Media and Entertainment"]:
        sector = "Communication Services"
    elif industry_group == "Power and Utilities":
        sector = "Utilities"
    elif industry_group in ["Investment Trusts", "Real Estate Management and Development"]:
        sector = "Real Estate"
        
    return sector
    

def lookup_industry_grouping(industry: str) -> str:
    # return the industry grouping based on the industry name
    industry_group = "Other"
    
    if industry in ["oil and gas", "coal"]:
        industry_group = "Consumables"
    elif industry in ["solar", "wind", "hydro", "uranium"]:
        industry_group = "Renewables"
    elif any(substr in industry for substr in ["agricultural", "chemical"]):
        industry_group = "Chemicals"
    elif "container" in industry:
        industry_group = "Containers and Packaging"
    elif any(substr in industry for substr in ["aluminum", "copper", "gold", "metal", "silver", "steel"]):
        industry_group = "Metals and Mining"
    elif any(substr in industry for substr in ["lumber", "forestry", "paper"]):
        industry_group = "Paper and Forest Products"
    elif any(substr in industry for substr in ["aerospace", "building", "construction", "industrial", "electrical components", "electrical equipment", "machinery", "trading"]):
        industry_group = "Capital Goods"
    elif any(substr in industry for substr in ["business", "consulting", "employment", "research", "security"]):
        industry_group = "Commercial and Professional Services"
    elif any(substr in industry for substr in ["airlines", "airport", "logistics", "marine", "rail"]):
        industry_group = "Transportation"
    elif any(substr in industry for substr in ["auto", "motor", "truck", "vehicle"]):
        industry_group = "Automobiles and Components"
    elif any(substr in industry for substr in ["apparel manufacturing", "appliances", "consumer electronics", "household appliances", "foot", "luxury", "textile"]):
        industry_group = "Consumer Durables and Apparel"
    elif any(substr in industry for substr in ["casino", "education", "lodging", "gambling", "hotel", "leisure", "personal services", "restaurant", "travel"]):
        industry_group = "Consumer Services"
    elif "retail" in industry:
        industry_group = "Consumer Discretionary Distribution and Retail"
    elif any(substr in industry for substr in ["food distribution", "store", "grocery"]):
        industry_group = "Consumer Staples Distribution and Retail"
    elif any(substr in industry for substr in ["breweries", "beverage", "confectioners", "packaged foods", "farm products", "tobacco", "wineries"]):
        industry_group = "Food, Beverage and Tobacco"
    elif "house" in industry:
        industry_group = "Household and Personal Products"
    elif any(substr in industry for substr in ["biotechnology", "health", "medical", "pharmaceutical"]):
        industry_group = "Healthcare and Pharmaceuticals"
    elif "bank" in industry:
        industry_group = "Banks"
    elif any(substr in industry for substr in ["asset", "capital", "conglomerate", "credit", "finance", "financial", "invest", "shell"]):
        industry_group = "Financial Services"
    elif "insurance" in industry:
        industry_group = "Insurance"
    elif any(substr in industry for substr in ["internet", "information technology", "software"]):
        industry_group = "Software and Services"
    elif any(substr in industry for substr in ["communication", "computer", "electronic", "infrastructure", "instrument", "semiconductor", "technology"]):
        industry_group = "Technology Hardware and Equipment"
    elif "telecom" in industry:
        industry_group = "Telecommunication Services"
    elif any(substr in industry for substr in ["advert", "broadcast", "entertainment", "gaming", "media", "publish"]):
        industry_group = "Media and Entertainment"
    elif any(substr in industry for substr in ["power", "treatment", "utilities", "waste"]):
        industry_group = "Power and Utilities"
    elif "reit" in industry:
        industry_group = "Investment Trusts"
    elif any(substr in industry for substr in ["real estate", "rental", "property"]):
        industry_group = "Real Estate Management and Development"
    
    return industry_group

def consolidate_industries() -> None:
    
    industries = []
    
    for industry in stocks.distinct("industry"):
        old_industry = industry.strip().replace("\u2014", " - ").lower()
        industry_components = old_industry.split(" - ")
        if len(industry_components) > 1:
            root_industry, sub_industry = industry_components[0].strip(), industry_components[1].strip()
            
            if root_industry == "beverages":
                if "brewers" in sub_industry.lower():
                    consolidated_industry = "Breweries"
                elif "wineries" in sub_industry.lower():
                    consolidated_industry = "Wineries and Distilleries"
            elif root_industry == "drug manufacturers":
                if "generic" in sub_industry.lower():
                    consolidated_industry = "Generic Pharmaceuticals"
                elif "specialty" in sub_industry.lower():
                    consolidated_industry = "Specialty Pharmaceuticals"
            elif root_industry == "reit":
                if "healthcare" in sub_industry.lower():
                    consolidated_industry = "Healthcare REIT"
            elif root_industry == "software":
                if "infrastructure" in sub_industry.lower():
                    consolidated_industry = "Systems Software"
            elif root_industry == "utilities":
                if "electric" in sub_industry.lower():
                    consolidated_industry = "Electrical Utilities"
                elif "independent power producers" in sub_industry.lower():
                    consolidated_industry = "Independent Power Producers"
                elif "water" in sub_industry.lower():
                    consolidated_industry = "Water Utilities"    
            else:
                consolidated_industry = " ".join([sub_industry.capitalize(), " ".join([part.capitalize() for part in root_industry.split()])]).strip()
        else:
            if "oil & gas" in industry.lower():
                consolidated_industry = "Oil and Gas"
            elif "coal" in industry.lower():
                consolidated_industry = "Coal"
            else:
                consolidated_industry = industry.replace("&", "and").strip()
                
            industries.append(consolidated_industry)
        
    unique_industries = sorted(set(industries))
    for industry_idx, industry in enumerate(unique_industries):
        unique_industries[industry_idx] = " - ".join([industry, lookup_industry_grouping(industry.lower())])
    print(f"Num unique industries in the database: {len(unique_industries)}")

    with open("./server/data/unique_industries_consolidated.json", "w") as f:
        json.dump(unique_industries, f, indent=4)  

def append_industry_groupings():
    updated_count = 0

    for stock in stocks.find({}, {"_id": 1, "industry": 1}):
        raw_industry = stock.get("industry", "")
        if not raw_industry:
            continue

        # Normalize and process
        industry = raw_industry.strip().replace("\u2014", " - ").lower()
        industry_group = lookup_industry_grouping(industry)

        # Only update if different or missing
        stocks.update_one(
            {"_id": stock["_id"]},
            {"$set": {"industry_group": industry_group}}
        )
        updated_count += 1

    print(f"Updated industry group for {updated_count} stocks.")

def update_company_details() -> None:
    failed_tickers = []
    num_failed = 0
    
    if not os.path.exists("./server/data/asx_companies.csv"):
        filtered_data = format_company_listing("./server/data/company_list.csv")
    else:
        filtered_data = pd.read_csv("./server/data/asx_companies.csv")
        
    for row in tqdm(filtered_data.itertuples(), desc="Processing tickers", total=len(filtered_data)):
        ticker = row.ticker.strip()
        tqdm.write("\n" + f"="*10)
        tqdm.write(f"Processing {ticker}")
        
        if stocks.find_one({"ticker": ticker}):
            tqdm.write(f"Skipped {ticker} as it already exists in the database")
        else:
            company_info = get_company_info(ticker)
            
            if company_info is not None:
                stocks.insert_one({
                    "ticker": ticker,
                    "company_name": row.name,
                    "summary": company_info["summary"],
                    "website": row.website,
                    "cap": row.cap,
                    "sector": row.sector,
                    "industry": company_info["industry"]
                })
                print(f"Successfully inserted {ticker}")
            else:
                print(f"Skipped {ticker} due to invalid data")
                num_failed += 1
                failed_tickers.append(ticker)
            
    print(f"Failed to insert {num_failed} companies out of {len(filtered_data)} due to missing data")
    print(f"Failed tickers: {failed_tickers}")  
    
def update_stock_entry(item_id: str, field_data: dict, skip_existing: bool = False):
    #existing = search_collection(collection_id, ticker_formatted)
    #tqdm.write(f"Adding {ticker_formatted} to collection....")
    
    try:
        response = requests.patch(
        f"https://api.webflow.com/v2/collections/{collection_id}/items/{item_id}/live",
        headers = {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json"
        },
        json = {
            "fieldData": field_data
        }
        )
        
    except Exception as e:
        tqdm.write(f"Error: {e}")    
        
    response = response.json()
    print(response)
    
def get_all_stocks() -> list:
    
    access_token = os.getenv("WEBFLOW_API_KEY")
    
    offset = 0
    page_limit = 100
    collected_all = False
    all_items = []
    announcement_collection_id = os.getenv("WEBFLOW_STOCK_COLLECTION_ID")

    print("Beginning collection process....")

    while not collected_all:
        try:
            response = requests.get(
            f"https://api.webflow.com/v2/collections/{announcement_collection_id}/items/live",
            headers = {
                "Authorization": "Bearer " + access_token,
                "Content-Type": "application/json"
            },
            params = {
                "offset": offset
            }
        )
            
        except Exception as e:
            print(f"Error fetching from webflow: {e}")

        all_items.extend(response.json()["items"])
        
        if len(response.json()["items"]) < page_limit:
            collected_all = True
        else:
            offset += page_limit
    return sorted(all_items, key=lambda x: x["fieldData"]["ticker"])

def update_stocks(update_list: list, source: str = "webflow"):
    for stock in tqdm(update_list, "Processed stocks", len(update_list)):
        if source == "webflow":
            ticker = stock["fieldData"]["ticker"]
            existing_stock = stocks.find_one({"ticker": f"{ticker}.AX"})
            
            if existing_stock:
                field_data = stock["fieldData"]
                
                sector_id = search_collection(os.getenv("WEBFLOW_SECTOR_COLLECTION_ID"), existing_stock["sector"])
                industry_id = search_collection(os.getenv("WEBFLOW_INDUSTRY_COLLECTION_ID"), existing_stock["industry"])
                group_id = search_collection(os.getenv("WEBFLOW_INDUSTRY_GROUP_COLLECTION_ID"), existing_stock["industry_group"])
                
                field_data["company-sector"] = sector_id
                field_data["company-industry"] = industry_id
                field_data["company-industry-group"] = group_id
                field_data["website"] = existing_stock["website"]
                field_data["company-market-cap"] = existing_stock["cap"]
                
                update_stock_entry(stock["id"], field_data)

if __name__ == "__main__":
    
    #update_company_details()
    #consolidate_industries()
    #append_industry_groupings()
    
    #all_stocks = list(stocks.find({}))
    all_stocks = get_all_stocks()
    print(f"Discovered {len(all_stocks)}")

    '''
    for stock in all_stocks:
        stock_meta = stock["fieldData"]
        if stock_meta.get("company-industry-group", "") == "":
          
            subset_stocks.append(stock)
    '''
    
    update_stocks()