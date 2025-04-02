from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter, WebVTTFormatter, SRTFormatter, JSONFormatter
from youtube_transcript_api._transcripts import TranscriptList
from youtube_transcript_api.formatters import Formatter
from youtube_transcript_api.proxies import WebshareProxyConfig
from typing import Optional, Literal, List, Dict
import os
from dotenv import load_dotenv
import logging
import requests
import urllib3
import time
import random
from urllib.parse import urlparse
import http.cookiejar
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Also enable debug logging for urllib3 to see proxy connection details
logging.getLogger("urllib3.connectionpool").setLevel(logging.DEBUG)

load_dotenv()

# More realistic browser headers with dynamic values
def get_headers():
    chrome_version = f"{random.randint(100, 122)}.0.0.0"
    return {
        'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'sec-ch-ua': f'"Google Chrome";v="{chrome_version}", "Chromium";v="{chrome_version}", "Not=A?Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"'
    }

# Configure session with retries and backoff
def create_session():
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    
    # Add retry adapter to both HTTP and HTTPS
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Set headers
    session.headers.update(get_headers())
    
    return session

# Configure cookie handling
cookie_jar = http.cookiejar.CookieJar()

def validate_env_vars():
    """Validate required environment variables are present and properly formatted."""
    required_vars = {
        "WEBSHARE_PROXY_USERNAME": os.getenv("WEBSHARE_PROXY_USERNAME"),
        "WEBSHARE_PROXY_PASSWORD": os.getenv("WEBSHARE_PROXY_PASSWORD")
    }
    
    missing_vars = [k for k, v in required_vars.items() if not v]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
    
    return True

# Configure proxy at module level
proxy_config = None
session = None
if not validate_env_vars():
    logger.error("Environment validation failed. Service may not work properly.")
else:
    proxy_username = os.getenv("WEBSHARE_PROXY_USERNAME")
    proxy_password = os.getenv("WEBSHARE_PROXY_PASSWORD")
    
    # Configure proxy using dictionary format
    proxy_url = f"http://{proxy_username}:{proxy_password}@p.webshare.io:80"
    proxy_config = {
        "http": proxy_url,
        "https": proxy_url
    }
    
    # Create and configure session
    session = create_session()
    session.proxies = proxy_config
    session.cookies = cookie_jar
    
    # Configure YouTubeTranscriptApi with session
    YouTubeTranscriptApi.proxies = proxy_config
    YouTubeTranscriptApi.headers = session.headers
    YouTubeTranscriptApi.cookies = session.cookies
    logger.debug("Proxy and session configuration complete")

# Add random delay between requests with exponential backoff
last_request_time = 0
MIN_REQUEST_INTERVAL = 3  # increased minimum seconds between requests
MAX_RETRIES = 3
BASE_DELAY = 5

def wait_between_requests(retry_count=0):
    """Add a random delay between requests with exponential backoff."""
    global last_request_time, session
    current_time = time.time()
    time_since_last = current_time - last_request_time
    
    # Calculate delay with exponential backoff
    if retry_count > 0:
        delay = BASE_DELAY * (2 ** (retry_count - 1)) + random.uniform(1, 3)
    else:
        delay = max(0, MIN_REQUEST_INTERVAL - time_since_last) + random.uniform(1, 3)
    
    if delay > 0:
        logger.debug(f"Waiting {delay:.2f} seconds before next request (retry {retry_count})")
        time.sleep(delay)
    
    last_request_time = time.time()
    
    # Update session with new headers
    if session:
        session.headers.update(get_headers())
        YouTubeTranscriptApi.headers = session.headers

logger.debug(f"Environment variables: {dict(os.environ)}")
logger.debug(f"Proxy configuration: Username={proxy_username}@p.webshare.io:80")

app = FastAPI(title="YouTube Transcript Service")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "YouTube Transcript Service",
        "proxy_configured": proxy_config is not None
    }

@app.get("/transcript/{video_id}")
async def get_transcript(
    video_id: str, 
    language: Optional[str] = None,
    format: Optional[Literal["text", "vtt", "srt", "json"]] = None,
    preserve_formatting: bool = False
):
    try:
        if not proxy_config:
            logger.error("No proxy configuration available")
            raise HTTPException(
                status_code=503,
                detail="Proxy configuration not available. Service is temporarily unavailable."
            )
            
        logger.debug(f"Fetching transcript for video {video_id} with language {language}, format {format}")
        logger.debug(f"Using proxy: {proxy_config['http']}")
        
        last_error = None
        for retry in range(MAX_RETRIES):
            try:
                # Add delay between requests with exponential backoff
                wait_between_requests(retry)
                
                # First try to get the transcript in the requested language
                if language:
                    logger.debug(f"Attempting to fetch transcript in {language} (retry {retry})")
                    transcript = YouTubeTranscriptApi().fetch(
                        video_id, 
                        languages=[language],
                        preserve_formatting=preserve_formatting
                    )
                else:
                    logger.debug(f"Attempting to fetch transcript in English (retry {retry})")
                    transcript = YouTubeTranscriptApi().fetch(
                        video_id, 
                        languages=['en'],
                        preserve_formatting=preserve_formatting
                    )
                
                logger.debug(f"Successfully fetched transcript")
                
                # Format the transcript according to the requested format
                if format:
                    formatter = None
                    if format == "text":
                        formatter = TextFormatter()
                    elif format == "vtt":
                        formatter = WebVTTFormatter()
                    elif format == "srt":
                        formatter = SRTFormatter()
                    elif format == "json":
                        formatter = JSONFormatter()
                    
                    if formatter:
                        logger.debug(f"Formatting transcript as {format}")
                        formatted_text = formatter.format_transcript(transcript)
                        return {
                            "text": formatted_text,
                            "source": "youtube_transcript_api",
                            "format": format,
                            "video_id": video_id
                        }
                
                # Default formatting with timestamps
                logger.debug("Using default timestamp formatting")
                formatted_transcript = ""
                for entry in transcript:
                    start = float(entry['start'])
                    text = entry['text'].strip()
                    
                    minutes = int(start // 60)
                    seconds = int(start % 60)
                    timestamp = f"{minutes}:{seconds:02d}"
                    formatted_transcript += f"{timestamp} - {text}\n"
                
                return {
                    "text": formatted_transcript.strip(),
                    "source": "youtube_transcript_api",
                    "video_id": video_id
                }
                
            except Exception as e:
                error_str = str(e)
                logger.error(f"Error fetching transcript (retry {retry}): {error_str}")
                last_error = e
                
                if "429 Client Error: Too Many Requests" in error_str or "YouTube is blocking requests" in error_str or "/sorry/" in error_str:
                    if retry < MAX_RETRIES - 1:
                        logger.debug(f"Rate limited, retrying with longer delay (retry {retry})")
                        continue
                    raise HTTPException(
                        status_code=503,
                        detail="Service temporarily unavailable due to rate limiting. Please try again in a few minutes."
                    )
                elif "Connection refused" in error_str or "Connection timed out" in error_str:
                    if retry < MAX_RETRIES - 1:
                        logger.debug(f"Proxy connection error, retrying (retry {retry})")
                        continue
                    raise HTTPException(
                        status_code=503,
                        detail="Proxy connection error. Please try again later."
                    )
                else:
                    raise e
        
        # If we get here, we've exhausted all retries
        if last_error:
            raise last_error
                
    except HTTPException:
        raise
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error fetching transcript: {error_message}")
        
        if "Subtitles are disabled" in error_message:
            status_code = 404
            detail = "This video does not have subtitles or transcripts available."
        elif "Could not find transcript" in error_message:
            status_code = 404
            detail = f"No transcript available in the requested language: {language}"
        elif "Video unavailable" in error_message:
            status_code = 404
            detail = "The video is unavailable or does not exist."
        elif "YouTube is blocking requests from your IP" in error_message or "429" in error_message or "/sorry/" in error_message:
            status_code = 503
            detail = "Service temporarily unavailable due to rate limiting. Please try again in a few minutes."
        elif "Connection refused" in error_message or "Connection timed out" in error_message:
            status_code = 503
            detail = "Proxy connection error. Please try again later."
        else:
            status_code = 500
            detail = f"An error occurred while fetching the transcript: {error_message}"
            
        raise HTTPException(
            status_code=status_code,
            detail=detail
        )

@app.get("/languages/{video_id}")
async def list_languages(video_id: str):
    try:
        if not proxy_config:
            raise HTTPException(
                status_code=503,
                detail="Proxy configuration not available. Service is temporarily unavailable."
            )
            
        logger.debug(f"Listing languages for video {video_id}")
        
        try:
            transcript_list = YouTubeTranscriptApi().list(video_id)
            
            available_transcripts = []
            for transcript in transcript_list:
                available_transcripts.append({
                    "language": transcript.language,
                    "language_code": transcript.language_code,
                    "is_generated": transcript.is_generated,
                    "is_translatable": transcript.is_translatable,
                    "translation_languages": transcript.translation_languages
                })
            
            logger.debug(f"Found {len(available_transcripts)} available transcripts")
            return {
                "video_id": video_id,
                "available_transcripts": available_transcripts
            }
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error listing languages: {error_str}")
            
            if "429 Client Error: Too Many Requests" in error_str:
                # If rate limited, wait a bit and try again
                time.sleep(5)
                raise HTTPException(
                    status_code=503,
                    detail="Service temporarily unavailable. Please try again later."
                )
            else:
                raise e
                
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error listing languages: {error_message}")
        
        if "Video unavailable" in error_message:
            status_code = 404
            detail = "The video is unavailable or does not exist."
        elif "YouTube is blocking requests from your IP" in error_message or "429" in error_message:
            status_code = 503
            detail = "Service temporarily unavailable. Please try again later."
        else:
            status_code = 500
            detail = f"An error occurred while fetching available languages: {error_message}"
            
        raise HTTPException(
            status_code=status_code,
            detail=detail
        )

@app.get("/translate/{video_id}")
async def translate_transcript(
    video_id: str,
    target_language: str,
    source_language: Optional[str] = None,
    format: Optional[Literal["text", "vtt", "srt", "json"]] = None,
    preserve_formatting: bool = False
):
    try:
        if not proxy_config:
            raise HTTPException(
                status_code=503,
                detail="No proxy configuration available. Service is temporarily unavailable."
            )
            
        logger.debug(f"Translating transcript for video {video_id} to {target_language}")
        logger.debug(f"Using proxy: {proxy_config['http']}")
        
        try:
            # Get transcript list
            transcript_list = YouTubeTranscriptApi().list(video_id)
            
            # Find source transcript
            source_langs = [source_language] if source_language else ['en']
            transcript = transcript_list.find_transcript(source_langs)
            
            # Translate to target language
            translated = transcript.translate(target_language)
            transcript_data = translated.fetch()
            
            logger.debug(f"Successfully translated transcript")
            
            # Format the transcript according to the requested format
            if format:
                formatter = None
                if format == "text":
                    formatter = TextFormatter()
                elif format == "vtt":
                    formatter = WebVTTFormatter()
                elif format == "srt":
                    formatter = SRTFormatter()
                elif format == "json":
                    formatter = JSONFormatter()
                
                if formatter:
                    logger.debug(f"Formatting transcript as {format}")
                    formatted_text = formatter.format_transcript(transcript_data)
                    return {
                        "text": formatted_text,
                        "source": "youtube_transcript_api",
                        "format": format,
                        "video_id": video_id,
                        "source_language": transcript.language_code,
                        "target_language": target_language
                    }
            
            # Default formatting with timestamps
            formatted_transcript = ""
            for entry in transcript_data:
                start = float(entry['start'])
                text = entry['text'].strip()
                
                minutes = int(start // 60)
                seconds = int(start % 60)
                timestamp = f"{minutes}:{seconds:02d}"
                formatted_transcript += f"{timestamp} - {text}\n"
            
            return {
                "text": formatted_transcript.strip(),
                "source": "youtube_transcript_api",
                "video_id": video_id,
                "source_language": transcript.language_code,
                "target_language": target_language
            }
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error translating transcript: {error_str}")
            
            if "429 Client Error: Too Many Requests" in error_str or "YouTube is blocking requests" in error_str:
                raise HTTPException(
                    status_code=503,
                    detail="Service temporarily unavailable due to rate limiting. Please try again later."
                )
            elif "Connection refused" in error_str or "Connection timed out" in error_str:
                raise HTTPException(
                    status_code=503,
                    detail="Proxy connection error. Please try again later."
                )
            else:
                raise e
                
    except HTTPException:
        raise
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error translating transcript: {error_message}")
        
        if "Subtitles are disabled" in error_message:
            status_code = 404
            detail = "This video does not have subtitles or transcripts available."
        elif "Could not find transcript" in error_message:
            status_code = 404
            detail = f"No transcript available in the source language: {source_language}"
        elif "Translation not available" in error_message:
            status_code = 404
            detail = f"Translation to {target_language} is not available."
        elif "Video unavailable" in error_message:
            status_code = 404
            detail = "The video is unavailable or does not exist."
        elif "YouTube is blocking requests from your IP" in error_message or "429" in error_message:
            status_code = 503
            detail = "Service temporarily unavailable due to rate limiting. Please try again later."
        elif "Connection refused" in error_message or "Connection timed out" in error_message:
            status_code = 503
            detail = "Proxy connection error. Please try again later."
        else:
            status_code = 500
            detail = f"An error occurred while translating the transcript: {error_message}"
            
        raise HTTPException(
            status_code=status_code,
            detail=detail
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port) 