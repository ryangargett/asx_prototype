import asyncio
from app import process_announcement
import time


async def main():
    
    announcement =   {
        "dateTime": "28-Apr-2025 08:56:30",
        "fileId": "2A1592869",
        "code": "SYA",
        "isSensitive": "Y",
        "heading": "Moblan Drilling Results",
        "newsTypes": [
        "11001"
        ],
        "fileSize": 2487215,
        "pageCount": 30,
        "documentURL": "https://quoteapi.com/files/rtw/announcements/sya.asx/2A1592869.pdf"
    }
    
    await process_announcement(announcement)

if __name__ == "__main__":
    start_time = time.time()
    asyncio.run(main())
    end_time = time.time()
    print(f"Execution time: {(end_time - start_time):.4f} seconds")