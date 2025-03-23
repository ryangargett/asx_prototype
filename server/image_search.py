from decouple import config
from serpapi import GoogleSearch

api_key = config("SERP_KEY")

def get_url_from_keyword(keywords):
    valid_link = None
    while not valid_link:
        params = {
            "engine": "google",
            "q": keywords,
            "output": "json",
            "api_key": api_key,
            "tbm": "isch",
            "num": 1
        }

        search = GoogleSearch(params)
        results = search.get_dict()
        
        if len(results["images_results"]) > 0:
            valid_link = results["images_results"][0]["original"]
        
    return valid_link

#if __name__ == "__main__":
    #url = get_url_from_keyword("gold mining, stockpiles evaluation, metallurgical testing")
    #print(url)