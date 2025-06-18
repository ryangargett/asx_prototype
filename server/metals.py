import colorama
import json
import os
import requests

from pymongo import MongoClient

from dotenv import load_dotenv
load_dotenv()

from logging_init import logger

mongo_client = MongoClient(os.getenv("MONGODB_KEY"))
    
db = mongo_client["main"]
metals = db["metals"]

'''
with open("./server/data/metal_prices.json", "r") as f:
    metal_list = json.load(f)
    
metals.insert_many(metal_list)
'''
metal_key = os.getenv("METAL_KEY")

def _get_prices(symbols: list) -> dict:
    params = {
        "access_key": metal_key,
        "symbols": ",".join(symbols)
    }
    
    try:
        response = requests.get(
            "https://metals-api.com/api/latest", 
            params=params
        )
        data = response.json()
    except Exception as e:
        logger.error(f"Unexpected error fetching metal prices: {e}")
        return {}
    return data["rates"]   

def update_metal_prices() -> None:
    
    commodities = list(metals.find({}, {"symbol": 1}))
    symbols = [commodity["symbol"] for commodity in commodities]
    logger.info(f"Attempting update for {len(symbols)} commodities")
    
    num_successful = 0
    
    for ii in range(0, len(symbols), 10):
        symbols_batch = symbols[ii:ii+10]
        logger.info(f"Updating commodity batch: {symbols_batch}")
        prices = _get_prices(symbols_batch)
        
        for symbol, price in prices.items():
            if symbol in symbols_batch:
                
                try:
                    price = 1 / price # ensure price is properly converted to $ / unit
                    cf = metals.find_one({"symbol": symbol})["cf"]
                    metals.update_one({"symbol": symbol}, {"$set": {"price": round(price, 4),
                                                                    "adjusted_price": round((price / cf), 4)}})
                    num_successful += 1
                except Exception as e:
                    logger.error(f"Error updating {symbol}: {e}")
                    
    logger.info(f"Successfully updated {num_successful} / {len(symbols)} commodities")