
import json
import openai
import os
import requests
import uuid

import asyncio

from asyncio import sleep, timeout, TimeoutError, Semaphore
from httpx import Timeout, ConnectError, ReadTimeout
from typing import Optional

import pandas as pd
from logging import Logger

from openai import AsyncClient, RateLimitError
from decouple import config
from pypdf import PdfReader
from webflow.client import Webflow

openai_client = AsyncClient(
    api_key=config("OPENAI_KEY"),
    timeout=Timeout(30.0, read=60.0)
)

openai_semaphore = Semaphore(5)

async def summarize_content(
    content: str,
    logger: Logger,
    company: Optional[str] = "", 
    model: Optional[str] = "o3-mini-2025-01-31",
    system_prompt: Optional[str] = None,
    prompt: Optional[str] = None) -> dict:
    
    if not system_prompt:
        system_prompt = """You are a highly intelligent AI assistant trained to write journal articles on technical topics."""

    if not prompt:
        if model == "o3-mini-2025-01-31":
            prompt = f"""Provide a comprehensive summary for the following announcement released from company {company}. This summary should be appropriate for a finance blog targeted towards beginner traders. The summary should include all relevant information from the announcement and be written in a journalistic style. The summary should be concise and informative, including all relevant technical indicators. Never refer to the article as a summary or concise overview. This article cannot include the ASX ticker in any way, only refer to the company by its' legal name (for example BHP GROUP LIMITED instead of ASX:BHP) Include a section for a bullish vs bearish sentiment based on the provided news. Format as rich text logically seperating into paragraphs based on typical journal structure, but do not include any subheadings or special formatting..\n\nCOMPANY ANNOUNCEMENT: {content}\n\nSUMMARY:"""
        else:
            prompt = f"""You are a senior experienced investor that is teaching a beginner investor good strategies to perform well in securing trades. This investor has a basic understanding of the stock market and economic principles, but is still extremely inexperienced and requires your expertise and guidance. You are given a company annoucement published in the Australia Securities Exchange (ASX). The announcement is subdivided into pages which are delineated by **PAGE [NUMBER] CONTENT:**. \n\nCOMPANY ANNOUNCEMENT: {content} \n\nFormat your response like a typical journal article. Capture all relevant details contained in the announcement. You should favour more journalistic language and structure over technical jargon whilst providing a summary for the provided article. Avoid bullet points. Only information that is helpful for the beginner investor should be included. Context and tips for the beginner investor should also be included where relevant based on the information provided. Any advice given should not directly address the beginner investor. For example instead of: \"For beginner investors, acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Use: \"Acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Do not provide weblinks or urls. Only seperate paragraphs for clearly different ideas, and favour paragraph length over conciseness. The proportion of paragraphs with additional investor advice should not exceed 50%. The assignment should be based on how important providing additional context or information is for the beginner investor. Always use present perfect tense. For example instead of: \"Gold prices surged past $2,500 per ounce\" Use: \"Gold prices have surged past $2,500 per ounce\". Do not including any headings or subheadings in your summary.\n\nSUMMARY:"""
    
    prompt = prompt.replace("&lt;&lt;ARTICLE&gt;&gt", content) 
    
    async with openai_semaphore:
        try:
            response = await openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as e:
            logger.error(f"Error summarizing content: {e}")
            return None

    if response:
        return response.choices[0].message.content
    else:
        return None
    
def read_pdf(in_file: str, page_limit: int = None) -> str:
    
    reader = PdfReader(in_file)
    page_content = ""
    
    pages = reader.pages[:page_limit] if page_limit is not None else reader.pages
    
    for idx, page in enumerate(pages):
        page_content += f"\n**PAGE {idx + 1} CONTENT:**\n" + page.extract_text().strip()
        
    return page_content