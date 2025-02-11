import requests
import yfinance as yf
import pandas as pd
import io

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
        
        sector = info.get("sector", "N/A")
        if sector != "N/A":
            return {
                "ticker": ticker,
                "company_name": info.get("longName", "N/A"),
                "sector": sector,
                "subsector": info.get("industry", "N/A"),
                "summary": info.get("longBusinessSummary", "N/A")
            }
        else:
            return None
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return None