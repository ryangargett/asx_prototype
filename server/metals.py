import colorama
import json
import os
import requests

import random

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

def standardize_metal_prices(metals: dict, legal_metals: list) -> dict:
    
    metal_lookup = {metal["name"]: metal for metal in metals}
    
    standardized_metals = []
    
    for metal_name in legal_metals:
        metal = metal_lookup.get(metal_name)
        if metal:
            metal["price"], metal["unit"] = _convert_to_units(metal["name"], metal["price"], metal["unit"])
            metal["price"] = round(metal["price"], 2)
            standardized_metals.append(metal)      
            
    return standardized_metals 

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
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Unexpected error fetching metal prices: {e}")
        return {}
    return data["rates"]   

def _get_color(pct_change: float) -> str:
    if pct_change > 0:
        return "#2ecc71"
    elif pct_change < 0:
        return "#e74c3c"
    else:
        return "#AAAAAA"

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
                    price = 1 / price  # ensure price is properly converted to $ / unit
                    metal = metals.find_one({"symbol": symbol})
                    
                    last_price = metal.get("price", 0.0) # retrieve previous update's price for pct change etc.
                    if last_price is None:
                        last_price = 0.0
                    
                    new_price = round(price, 4)
                    new_adjusted_price = round((price / metal["cf"]), 4)
                    
                    raw_change = round(new_price - last_price, 2)
                    pct_change = round(((new_price - last_price) / (last_price + 1e-9)) * 100, 2) # avoid division by 0
                    
                    metals.update_one(
                        {"symbol": symbol},
                        {"$set": {
                            "price": new_price,
                            "adjusted_price": new_adjusted_price,
                            "last_price": last_price,
                            "raw_change": raw_change,
                            "pct_change": pct_change,
                            "color": _get_color(pct_change)
                        }}
                    )
                    num_successful += 1
                except Exception as e:
                    logger.error(f"Error updating {symbol}: {e}")
                    
    logger.info(f"Successfully updated {num_successful} / {len(symbols)} commodities")
    
if __name__ == "__main__":
    update_metal_prices()