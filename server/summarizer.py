
import json
import openai
import os
import requests
import uuid

from typing import Optional

import pandas as pd

from decouple import config
from pypdf import PdfReader
from webflow.client import Webflow

from image_search import get_url_from_keyword


def suggest_image_kwords(company: str, title: Optional[str] = "", model: Optional[str] = "o3-mini-2025-01-31", user_prompt: Optional[str] = None) -> str:
    
    client = openai.Client(api_key=config("OPENAI_KEY"))
    
    #system_prompt = """You are a highly intelligent AI assistant trained to extract company information from a technical report."""
    #user_prompt = f"""Determine the ASX company(s) mentioned in this report. Provide a list of the companies mentioned in the report. Provide AT MAXIMUM THREE related companies, ordered by relevance. The list should be formatted as a #string of comma seperated company names. Do not include any punctuation or special characters in the company names. Do not include any companies that are not mentioned in the report. Do not include any companies that are not listed #on the ASX. Do not include any companies that are not relevant to the report. COMPANY ANNOUNCEMENT: {content}\n\nCOMPANIES:"""
    
    #response = client.chat.completions.create(
    #    model="gpt-4o-mini",
    #    messages=[
    #        {"role": "system", "content": system_prompt},
    #        {"role": "user", "content": user_prompt},
    #    ]
    #)
    
    #suggested_companies = response.choices[0].message.content
    #companies = suggested_companies.split(", ")
    #if len(companies) > 3:
    #    suggested_companies = ", ".join([f"{company} ASX" for company in companies[:3]])
    #print(suggested_companies)
    
    system_prompt = "You are a highly intelligent AI assistant trained to generate keywords based on provided ASX company(s)."
    
    if not user_prompt:
        if model == "o3-mini-2025-01-31":
            f"Provide a keyword that can be used to search for an appropriate cover image for an announcement from company {company} with the title: {title}. The keyword should be relevant to the sector the company operates but be vague enough to yield an image appropriate for an article on a news blog. Suggest words that lead to high quality stock images. ONLY PROVIDE THE KEYWORDS WITH NO OTHER JUSTIFICATION OR EXPLANATION. For example, \"Gold Mining\" or \"Uranium Strip Mining\".\n\nKEYWORD:"
        else:
            user_prompt = f"""Provide a list of 3 keywords that could be used to search for an image relevant to the provided ASX companies. In the event that multiple companies are provided, the keywords should be most relevant to the first company, then the second company, and finally the third. This list should be formatted as a string of comma seperated keywords / phrases. These keywords MUST be completely associated with the provided company(s), and should not reference other companies, projects or otherwise conflicting data. The keywords must be as generic as possible whilst still relating to the given company. As an example, you are provided a company announcement from Clara Resources (ASX:C7A). This company primarily operates in the coal coking, cobalt mining and nickel mining sectors. Therefore, keywords associated with this company could be \"coal coking, cobalt mining, nickel mining\". Do not generate any keywords associated with the ASX, Australian Stock Market, Finance or Stock Market. Avoid keywords that could lead to tabular data. Do not include any punctuation or special characters in the keywords. DO NOT GENERATE MORE THAN THREE KEYWORDS.\n\nCOMPANY: {company}\n\nKEYWORDS:"""
        
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    
    
    suggested_image_kwords = response.choices[0].message.content
    return suggested_image_kwords

def suggest_title(content: str, company: Optional[str] = "", model: Optional[str] = "o3-mini-2025-01-31", user_prompts: Optional[dict] = None) -> tuple[str]:
    """Generates short and long form title for technical ASX company announcements using a configurable LLM endpoint (defaults to gpt-4o-m)

    Args:
        content (str): transcript of the company announcement including labeled pages
        company (str, optional): corresponding ASX company ticker
        model (str, optional): _description_. Defaults to "gpt-4o-m".
        user_prompt (dict, optional): _description_. Provided collection of user prompt, if not provided, default prompts are used compatible with RLHF models.

    Returns:
        short_title (str): short form title (constrained to < 20 words)
        long_title (str): long form title 
    """    
    
    client = openai.Client(api_key=config("OPENAI_KEY"))
    system_prompt = """You are a highly intelligent AI assistant trained to write journal articles on technical topics."""
    
    
    if not user_prompts:
        if model == "o3-mini-2025-01-31":
            user_prompts = {
                "short": f"Suggest an SEO-optimized title for the following company {company} announcement appropriate for a finance blog targeted towards beginner traders. This title cannot exceed 60 characters. The title should include critical financial information if needed and summarise all findings and crucial information from the announcement whilst being attractive and enticing to new users \n\nCOMPANY ANNOUNCEMENT: {content}\n\nSUGGESTED TITLE:",
                "long": f"Suggest an SEO-optimized title for the following company {company} announcement appropriate for a finance blog. The title should include critical financial information if needed and summarise all findings and crucial information from the announcement whilst being attractive and enticing to new users. \n\nCOMPANY ANNOUNCEMENT: {content}\n\nSUGGESTED TITLE:",
    }
        else:
            user_prompts = {
                "short": f"""Provide a suggested short-form title appropriate for an article thumbnail based on the provided announcement and ASX ticker. This title should include relevant technical indicators / statistics, the company name, and the main topic of the announcement. The title should be concise and informative. This title MUST NOT EXCEED 60 CHARACTERS AND BE SEO OPTIMIZED. Do not exceed 60 characters. Do not include any punctuation or special characters in the title. \n\nEXAMPLES: \n- Warriedar Resources Reports Strong Antimony Recovery Results from Ricciardo Project \n- Great Boulder Resources Hits 8m @ 7.59g/t Au at Saltbush Prospect, Side Well Gold Project, Western Australia \n- Critical Resources Hits 34.9m @ 1.02% Li₂O at Mavis Lake Project, Ontario\n\nCOMPANY TICKER: {company}\n\nCOMPANY ANNOUNCEMENT: {content}\n\nSUGGESTED TITLE:""",
                "long": f"""Provide a suggested title for the article based on the provided announcement and ASX ticker. This title should include relevant technical indicators / statistics, the company name, and the main topic of the announcement. The title should be concise and informative. Do not include any punctuation or special characters in the title. \n\nEXAMPLES: \n- Warriedar Resources Reports Strong Antimony Recovery Results from Ricciardo Project \n- Great Boulder Resources Hits 8m @ 7.59g/t Au at Saltbush Prospect, Side Well Gold Project, Western Australia \n- Critical Resources Hits 34.9m @ 1.02% Li₂O at Mavis Lake Project, Ontario\n\nCOMPANY TICKER: {company}\n\nCOMPANY ANNOUNCEMENT: {content}\n\nSUGGESTED TITLE:""", 
            }
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompts["short"]},
        ]
    )
    
    short_title = response.choices[0].message.content
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompts["long"]},
        ]
    )
    
    long_title = response.choices[0].message.content
    
    return short_title, long_title

def summarize_content(content: str, company: Optional[str] = "", model: Optional[str] = "o3-mini-2025-01-31", prompt: Optional[str] = None) -> dict:
    client = openai.Client(api_key=config("OPENAI_KEY"))
    
    system_prompt = """You are a highly intelligent AI assistant trained to write journal articles on technical topics."""
    
    '''user_prompt_a = f"""Provide a summary article for the following ASX company announcement. The announcement is subdivided into pages which are delineated by **PAGE [NUMBER] CONTENT:**. \n\nCOMPANY ANNOUNCEMENT: {content} \n\nFormat your response like a typical journal article. Capture all relevant details contained in the announcement. Your target audience are casual investors that have a basic understanding of the stock market and economic principles. You should favour more journalistic language and structure over technical jargon whilst providing a summary for the provided article. Avoid bullet points. Every included paragraph should summarize a key idea and be formatted in accordance with news article writing. Only information that is helpful for casual investors should be included. Do not provide weblinks or urls. Only seperate paragraphs for clearly different ideas, and favour paragraph length over conciseness. Always use present perfect tense. For example instead of: \"Gold prices surged past $2,500 per ounce\" Use: \"Gold prices have surged past $2,500 per ounce\". Do not including any headings or subheadings in your summary.\n\nSUMMARY:"""
    
    user_prompt_b = f"""You are a senior experienced investor that is teaching a beginner investor good strategies to perform well in securing trades. This investor has a basic understanding of the stock market and economic principles, but is still extremely inexperienced and requires your expertise and guidance. You are given a company annoucement published in the Australia Stock Exchange (ASX). The announcement is subdivided into pages which are delineated by **PAGE [NUMBER] CONTENT:**. \n\nCOMPANY ANNOUNCEMENT: {content} \n\nFormat your response like a typical journal article. Capture all relevant details contained in the announcement. You should favour more journalistic language and structure over technical jargon whilst providing a summary for the provided article. Avoid bullet points. Only information that is helpful for the beginner investor should be included. Context and tips for the beginner investor should also be included where relevant based on the information provided. Do not provide weblinks or urls. Only seperate paragraphs for clearly different ideas, and favour paragraph length over conciseness. Always use present perfect tense. For example instead of: \"Gold prices surged past $2,500 per ounce\" Use: \"Gold prices have surged past $2,500 per ounce\". Do not including any headings or subheadings in your summary.\n\nSUMMARY:"""
    
    user_prompt_c = f"""You are a senior experienced investor that is teaching a beginner investor good strategies to perform well in securing trades. This investor has a basic understanding of the stock market and economic principles, but is still extremely inexperienced and requires your expertise and guidance. You are given a company annoucement published in the Australia Securities Exchange (ASX). The announcement is subdivided into pages which are delineated by **PAGE [NUMBER] CONTENT:**. \n\nCOMPANY ANNOUNCEMENT: {content} \n\nFormat your response like a typical journal article. Capture all relevant details contained in the announcement. You should favour more journalistic language and structure over technical jargon whilst providing a summary for the provided article. Avoid bullet points. Only information that is helpful for the beginner investor should be included. Context and tips for the beginner investor should also be included where relevant based on the information provided. Any advice given should not directly address the beginner investor. For example instead of: \"For beginner investors, acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Use: \"Acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Do not provide weblinks or urls. Only seperate paragraphs for clearly different ideas, and favour paragraph length over conciseness. Always use present perfect tense. For example instead of: \"Gold prices surged past $2,500 per ounce\" Use: \"Gold prices have surged past $2,500 per ounce\". Do not including any headings or subheadings in your summary.\n\nSUMMARY:"""''' 
    
    if not prompt:
        if model == "o3-mini-2025-01-31":
            prompt = f"""Provide a comprehensive summary for the following announcement released from company {company}. This summary should be appropriate for a finance blog targeted towards beginner traders. The summary should include all relevant information from the announcement and be written in a journalistic style. The summary should be concise and informative, avoiding technical jargon but including all relevant technical indicators. Include a section for a bullish vs bearish sentiment based on the provided news. Format as rich text logically seperating into paragraphs based on typical journal structure.\n\nCOMPANY ANNOUNCEMENT: {content}\n\nSUMMARY:"""
        else:
            prompt = f"""You are a senior experienced investor that is teaching a beginner investor good strategies to perform well in securing trades. This investor has a basic understanding of the stock market and economic principles, but is still extremely inexperienced and requires your expertise and guidance. You are given a company annoucement published in the Australia Securities Exchange (ASX). The announcement is subdivided into pages which are delineated by **PAGE [NUMBER] CONTENT:**. \n\nCOMPANY ANNOUNCEMENT: {content} \n\nFormat your response like a typical journal article. Capture all relevant details contained in the announcement. You should favour more journalistic language and structure over technical jargon whilst providing a summary for the provided article. Avoid bullet points. Only information that is helpful for the beginner investor should be included. Context and tips for the beginner investor should also be included where relevant based on the information provided. Any advice given should not directly address the beginner investor. For example instead of: \"For beginner investors, acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Use: \"Acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Do not provide weblinks or urls. Only seperate paragraphs for clearly different ideas, and favour paragraph length over conciseness. The proportion of paragraphs with additional investor advice should not exceed 50%. The assignment should be based on how important providing additional context or information is for the beginner investor. Always use present perfect tense. For example instead of: \"Gold prices surged past $2,500 per ounce\" Use: \"Gold prices have surged past $2,500 per ounce\". Do not including any headings or subheadings in your summary.\n\nSUMMARY:"""
    
    prompt = prompt.replace("&lt;&lt;ARTICLE&gt;&gt", content)  
        
    '''
    response_a = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt_a},
        ]
    )
    
    response_b = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt_b},
        ]
    )
    
    response_c = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt_c},
        ]
    )
    '''
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
    )
    
    summarized_content = response.choices[0].message.content
    return summarized_content
    
def read_pdf(in_file: str) -> str:
    
    reader = PdfReader(in_file)
    page_content = ""
    
    for idx, page in enumerate(reader.pages):
        page_content += f"\n**PAGE {idx + 1} CONTENT:**\n" + page.extract_text().strip()
        
    return page_content

def push_to_site(metadata: dict) -> None:
    access_token="089c44a7073873cc6538e7951b6645522883561c4bca830af93961029f49c353"
    collection_id = "67ce9969e21d3fd4c6f5ba90"

    hash = uuid.uuid4().hex

    response = requests.post(
        f"https://api.webflow.com/v2/collections/{collection_id}/items/live",
        headers = {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json"
        },
        json = {
            "fieldData": {
                "name": metadata['short_title'],
                "title": metadata['long_title'],
                "short-title": metadata['short_title'],
                "content": metadata['content'],
                "hash-value": hash,
                "summary": metadata['summary'],
                "image-url": metadata['image_url'],
                "document-url": "https://rtwasxreports.s3.ap-southeast-2.amazonaws.com/003723bd2c7c467520700acbdd97f81889194f63a0d6ce785ee6fc0412e2d11a.pdf"
            }
        }
    )
    
    print(response)

if __name__ == "__main__":
    company = "ASX:HTM"
    parsed_content = read_pdf("examples/example.pdf")
    
    prompt = f"Provide a comprehensive summary for the following announcement released from company {company}. This summary should be appropriate for a finance blog targeted towards beginner traders. The summary should include all relevant information from the announcement and be written in a journalistic style. The summary should be concise and informative, avoiding technical jargon but including all relevant technical indicators. Include a section for a bullish vs bearish sentiment based on the provided news. Format as rich text logically seperating into paragraphs based on typical journal structure.\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUMMARY:"
    
    content = summarize_content(parsed_content, "o3-mini-2025-01-31", prompt)
    
    prompt = f"Provide a short (maximum 50 word) summary for the following announcement released from company {company}. This summary should be appropriate for a finance blog targeted towards beginner traders.\n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUMMARY:"
    
    summary = summarize_content(parsed_content, "o3-mini-2025-01-31", prompt)
    
    user_prompts = {
        "short": f"Suggest an SEO-optimized title for the following company {company} announcement appropriate for a finance blog targeted towards beginner traders. This title cannot exceed 60 characters. The title should include critical financial information if needed and summarise all findings and crucial information from the announcement whilst being attractive and enticing to new users \n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUGGESTED TITLE:",
        "long": f"Suggest an SEO-optimized title for the following company {company} announcement appropriate for a finance blog. The title should include critical financial information if needed and summarise all findings and crucial information from the announcement whilst being attractive and enticing to new users. \n\nCOMPANY ANNOUNCEMENT: {parsed_content}\n\nSUGGESTED TITLE:",
    }
    
    short_title, long_title = suggest_title(parsed_content, company, "o3-mini-2025-01-31", user_prompts)
    
    image_prompt = f"Provide a keyword that can be used to search for an appropriate cover image for an announcement from company {company} with the title: {short_title}. The keyword should be relevant to the sector the company operates but be vague enough to yield an image appropriate for an article on a news blog. Suggest words that lead to high quality stock images. ONLY PROVIDE THE KEYWORDS WITH NO OTHER JUSTIFICATION OR EXPLANATION. For example, \"Gold Mining\" or \"Uranium Strip Mining\".\n\nKEYWORDS:"
    
    k_words = suggest_image_kwords(company, model = "o3-mini-2025-01-31", user_prompt = image_prompt)
    print(k_words)
    url = get_url_from_keyword(k_words)
    print(url)
    
    metadata = {
        "company": company,
        "content": content,
        "summary": summary,
        "short_title": short_title,
        "long_title": long_title,
        "image_url": url
    }

    #metadata = json.loads(open("./examples/metadata.json", "r").read())
    print(metadata['summary'])
    
    push_to_site(metadata)
    
    with open(f"./examples/metadata.json", "w") as out_file:
        json.dump(metadata, out_file)
    
    