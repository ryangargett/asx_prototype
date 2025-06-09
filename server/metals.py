import colorama
import json
import os
import requests

from logging import getLogger, LogRecord, Formatter, INFO, StreamHandler
from pymongo import MongoClient
from tqdm import tqdm

from dotenv import load_dotenv
load_dotenv()

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

mongo_client = MongoClient(os.getenv("MONGODB_KEY"))

# Check if cluster is connected
try:
    mongo_client.admin.command('ping')
    logger.info("MongoDB connection successful")
except Exception as e:
    logger.error(f"MongoDB connection failed - {e}")
    
db = mongo_client["main"]
metals = db["metals"]

with open("./server/data/metal_prices.json", "r") as f:
    metal_list = json.load(f)
    
metals.insert_many(metal_list)

metal_key = os.getenv("METAL_KEY")
    
def _get_prices(symbols: list) -> dict:
    params = {
        "access_key": metal_key,
        "symbols": ",".join(symbols)
    }

    response = requests.get(
        "https://metals-api.com/api/latest", 
        params=params
    )
    data = response.json()
    return data["rates"]
    

def update_metal_prices(symbols: list) -> None:
    
    for ii in range(0, len(symbols), 10):
        symbols_batch = symbols[ii:ii+10]
        prices = _get_prices(symbols_batch)
        for symbol, price in prices.items():
            if symbol in symbols_batch:
                price = 1 / price # ensure price is properly converted to $ / unit
                cf = metals.find_one({"symbol": symbol})["cf"]
                metals.update_one({"symbol": symbol}, {"$set": {"price": round(price, 4),
                                                                "adjusted_price": round((price / cf), 4)}})

if __name__ == "__main__":
    valid_metals = list(metals.find({}, {"symbol": 1}))
    symbols = [symbol["symbol"] for symbol in valid_metals]
    print(update_metal_prices(symbols))