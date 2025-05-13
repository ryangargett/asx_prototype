import os
import json

import pandas as pd
import regex as re

from pymongo import MongoClient
from scraperapi_sdk import ScraperAPIClient
from collections import Counter
from tqdm import tqdm

mongo_client = MongoClient(os.getenv("MONGODB_KEY"))

# Check if cluster is connected
try:
    mongo_client.admin.command('ping')
    print("MongoDB connection: Successful")
except Exception as e:
    print(f"MongoDB connection: Failed - {e}")
    
db = mongo_client["main"]
stocks = db["stocks_new"]
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

def consolidate_industries() -> None:
    for industry in stocks.distinct("industry"):
        industry = industry.strip().replace("\u2014", " - ")

def update_company_details() -> None:
        
    access_token = os.getenv("WEBFLOW_API_KEY")
    collection_id = "67e8ae8d2f21aadc762733b1"
    
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
if __name__ == "__main__":
    
    #update_company_details()
    consolidate_industries()
    
    unique_sectors = stocks.distinct("sector")
    print(f"Num unique sectors in the database: {len(unique_sectors)}")
    print(f"Unique sectors: {unique_sectors}")
    
    unique_industries = stocks.distinct("industry")
    print(f"Num unique sectors in the database: {len(unique_industries)}")
    unique_industries.sort()
    
    with open("./server/data/unique_industries.json", "w") as f:
        json.dump(unique_industries, f, indent=4)
    
    #get_company_info()
    
    #get_energy_sector_industries()
    #get_tickers_by_sector_and_industry("Energy", "Specialty Business Services")
    #et_tickers_by_sector_and_industry("Materials", "Copper")
    
    '''
    legal_stocks_energy = [
    "AEE", "AEL", "AGE", "ALD", "BKY", "BMN", "BOE", "BPT", "COI", "CRD",
    "CVN", "DYL", "EEG", "ERA", "HZN", "KAR", "LOT", "NHC", "NXG", "OMA",
    "PDN", "PEN", "STO", "STX", "TBN", "VEA", "WDS", "WHC", "YAL"
    ]
    
    legal_stocks_material = [
        "29M", "A11", "A1M", "A4N", "AAI", "AAR", "ADT", "AIS", "AKM", "ALK",
        "AMC", "AMI", "ARR", "ARU", "ASL", "ATR", "AUC", "AVL", "AZY", "BC8",
        "BCI", "BCK", "BCN", "BGL", "BHP", "BIS", "BKW", "BOC", "BRE", "BRI",
        "BRL", "BSL", "BTR", "CAA", "CAY", "CHN", "CIA", "CMM", "CRN", "CSC",
        "CTM", "CVV", "CXO", "CYL", "DEG", "DGL", "DLI", "DRR", "DRX", "DVP",
        "EGR", "EMR", "ENR", "EQR", "ETM", "EVN", "FEX", "FFM", "FMG", "GG8",
        "GMD", "GNG", "GOR", "GRR", "GRX", "HCH", "HRZ", "IGO", "ILU", "IMA",
        "IMD", "INR", "IPL", "IPX", "JHX", "JMS", "KCN", "KLL", "LCY", "LIN",
        "LLL", "LRV", "LTR", "LYC", "MAC", "MAH", "MAU", "MDX", "MEI", "MEK",
        "MGX", "MIN", "MLX", "MM8", "MMI", "MRL", "NEM", "NIC", "NMG", "NST",
        "NTU", "NUF", "OBM", "OMH", "ORA", "ORI", "ORN", "PDI", "PGH", "PLS",
        "PMT", "PNR", "POL", "PRG", "PRN", "PRU", "PTN", "PTR", "QGL", "QPM",
        "RHI", "RIO", "RMS", "RND", "RNU", "RRL", "RSG", "RXL", "S32", "SBM",
        "SFR", "SGM", "SMI", "SMR", "SPR", "STA", "STK", "SVL", "SVM", "SX2",
        "SYA", "SYR", "TBR", "TCG", "TGM", "TLG", "TTM", "TTT", "TVN", "TZN",
        "USL", "VAU", "VSL", "VUL", "VYS", "WA1", "WAF", "WC8", "WGN", "WGX",
        "WIA", "ZIM"
    ]
    
    for stock in legal_stocks_energy:
        formatted_stock = stock + ".AX"
        details = stocks.find_one({"ticker": formatted_stock})
        if details:
            print(f"Ticker: {details['ticker']}, Company Name: {details['company_name']}, Industry: {details['industry']}")        
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
            elif "construction machinery" in details.get("industry", "").lower():
                industry = "Heavy Machinery"
            elif "freight" in details.get("industry", "").lower():
                industry = "Freight & Logistics"
            elif "agriculture" in details.get("industry", "").lower() or "farm" in details.get("industry", "").lower():
                industry = "Agriculture"
            else:
                industry = details.get("industry", "")
        else:
            print(f"No details found for ticker: {formatted_stock}")   
        try:
                response = requests.post(
                f"https://api.webflow.com/v2/collections/{collection_id}/items/live",
                headers = {
                    "Authorization": "Bearer " + access_token,
                    "Content-Type": "application/json"
                },
                json = {
                    "fieldData": {
                        "name": details["ticker"],
                        "ticker": details["ticker"],
                        "company": details["company_name"],
                        "sector": details["sector"],
                        "industry": industry,
                        "summary": details["summary"],            
                    }
                }
            )
            
                print(response.json())
                
        except Exception as e:
            print(f"Error uploading to webflow: {e}")
            '''