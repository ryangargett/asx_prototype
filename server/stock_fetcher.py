import requests
import yfinance as yf
import pandas as pd
import io

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