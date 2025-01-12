
import openai
import os

import pandas as pd

from decouple import config
from pypdf import PdfReader

def suggest_title(content: str) -> str:
    client = openai.Client(api_key=config("OPENAI_KEY"))
    system_prompt = """You are a highly intelligent AI assistant trained to write journal articles on technical topics."""
    user_prompt = f"""Provide a suggested title for the article based on the provided announcement. This title should include relevant technical indicators / statistics, the company name, and the main topic of the announcement. The title should be concise and informative. Do not include any punctuation or special characters in the title. \n\nEXAMPLES: \n- Warriedar Resources Reports Strong Antimony Recovery Results from Ricciardo Project \n- Great Boulder Resources Hits 8m @ 7.59g/t Au at Saltbush Prospect, Side Well Gold Project, Western Australia \n- Critical Resources Hits 34.9m @ 1.02% Li₂O at Mavis Lake Project, Ontario \n\nCOMPANY ANNOUNCEMENT: {content} \n\nSUGGESTED TITLE:"""
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    
    suggested_title = response.choices[0].message.content
    return suggested_title

def summarize_content(content: str, prompt: str = None) -> dict:
    client = openai.Client(api_key=config("OPENAI_KEY"))
    
    system_prompt = """You are a highly intelligent AI assistant trained to write journal articles on technical topics."""
    user_prompt_a = f"""Provide a summary article for the following ASX company announcement. The announcement is subdivided into pages which are delineated by **PAGE [NUMBER] CONTENT:**. \n\nCOMPANY ANNOUNCEMENT: {content} \n\nFormat your response like a typical journal article. Capture all relevant details contained in the announcement. Your target audience are casual investors that have a basic understanding of the stock market and economic principles. You should favour more journalistic language and structure over technical jargon whilst providing a summary for the provided article. Avoid bullet points. Every included paragraph should summarize a key idea and be formatted in accordance with news article writing. Only information that is helpful for casual investors should be included. Do not provide weblinks or urls. Only seperate paragraphs for clearly different ideas, and favour paragraph length over conciseness. Always use present perfect tense. For example instead of: \"Gold prices surged past $2,500 per ounce\" Use: \"Gold prices have surged past $2,500 per ounce\". Do not including any headings or subheadings in your summary.\n\nSUMMARY:"""
    
    user_prompt_b = f"""You are a senior experienced investor that is teaching a beginner investor good strategies to perform well in securing trades. This investor has a basic understanding of the stock market and economic principles, but is still extremely inexperienced and requires your expertise and guidance. You are given a company annoucement published in the Australia Stock Exchange (ASX). The announcement is subdivided into pages which are delineated by **PAGE [NUMBER] CONTENT:**. \n\nCOMPANY ANNOUNCEMENT: {content} \n\nFormat your response like a typical journal article. Capture all relevant details contained in the announcement. You should favour more journalistic language and structure over technical jargon whilst providing a summary for the provided article. Avoid bullet points. Only information that is helpful for the beginner investor should be included. Context and tips for the beginner investor should also be included where relevant based on the information provided. Do not provide weblinks or urls. Only seperate paragraphs for clearly different ideas, and favour paragraph length over conciseness. Always use present perfect tense. For example instead of: \"Gold prices surged past $2,500 per ounce\" Use: \"Gold prices have surged past $2,500 per ounce\". Do not including any headings or subheadings in your summary.\n\nSUMMARY:"""
    
    user_prompt_c = f"""You are a senior experienced investor that is teaching a beginner investor good strategies to perform well in securing trades. This investor has a basic understanding of the stock market and economic principles, but is still extremely inexperienced and requires your expertise and guidance. You are given a company annoucement published in the Australia Securities Exchange (ASX). The announcement is subdivided into pages which are delineated by **PAGE [NUMBER] CONTENT:**. \n\nCOMPANY ANNOUNCEMENT: {content} \n\nFormat your response like a typical journal article. Capture all relevant details contained in the announcement. You should favour more journalistic language and structure over technical jargon whilst providing a summary for the provided article. Avoid bullet points. Only information that is helpful for the beginner investor should be included. Context and tips for the beginner investor should also be included where relevant based on the information provided. Any advice given should not directly address the beginner investor. For example instead of: \"For beginner investors, acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Use: \"Acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Do not provide weblinks or urls. Only seperate paragraphs for clearly different ideas, and favour paragraph length over conciseness. Always use present perfect tense. For example instead of: \"Gold prices surged past $2,500 per ounce\" Use: \"Gold prices have surged past $2,500 per ounce\". Do not including any headings or subheadings in your summary.\n\nSUMMARY:"""
    
    if not prompt:
        prompt = f"""You are a senior experienced investor that is teaching a beginner investor good strategies to perform well in securing trades. This investor has a basic understanding of the stock market and economic principles, but is still extremely inexperienced and requires your expertise and guidance. You are given a company annoucement published in the Australia Securities Exchange (ASX). The announcement is subdivided into pages which are delineated by **PAGE [NUMBER] CONTENT:**. \n\nCOMPANY ANNOUNCEMENT: {content} \n\nFormat your response like a typical journal article. Capture all relevant details contained in the announcement. You should favour more journalistic language and structure over technical jargon whilst providing a summary for the provided article. Avoid bullet points. Only information that is helpful for the beginner investor should be included. Context and tips for the beginner investor should also be included where relevant based on the information provided. Any advice given should not directly address the beginner investor. For example instead of: \"For beginner investors, acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Use: \"Acknowledging how and why these securities are issued without additional approvals can shed light on corporate governance practices.\" Do not provide weblinks or urls. Only seperate paragraphs for clearly different ideas, and favour paragraph length over conciseness. The proportion of paragraphs with additional investor advice should not exceed 50%. The assignment should be based on how important providing additional context or information is for the beginner investor. Always use present perfect tense. For example instead of: \"Gold prices surged past $2,500 per ounce\" Use: \"Gold prices have surged past $2,500 per ounce\". Do not including any headings or subheadings in your summary.\n\nSUMMARY:"""
    else:
        prompt = prompt.replace("&lt;&lt;ARTICLE&gt;&gt", content)
        
    print(prompt)    
        
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
        model="gpt-4o-mini",
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

if __name__ == "__main__":
    
    parsed_content = read_pdf("examples/example.pdf")
    summarized_content = summarize_content(parsed_content)
    