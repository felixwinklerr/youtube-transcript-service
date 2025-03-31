from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter, WebVTTFormatter, SRTFormatter, JSONFormatter
from youtube_transcript_api._transcripts import TranscriptList
from youtube_transcript_api.formatters import Formatter
from youtube_transcript_api.proxies import WebshareProxyConfig
from typing import Optional, Literal, List
import os
from dotenv import load_dotenv
import logging
import requests
import urllib3
import random
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Also enable debug logging for urllib3 to see proxy connection details
logging.getLogger("urllib3.connectionpool").setLevel(logging.DEBUG)

load_dotenv()

# Configure proxy at module level
username = os.getenv("WEBSHARE_PROXY_USERNAME")
password = os.getenv("WEBSHARE_PROXY_PASSWORD")
proxy_hosts = os.getenv("WEBSHARE_PROXY_HOSTS", "").split(",")  # Multiple hosts separated by commas
proxy_ports = os.getenv("WEBSHARE_PROXY_PORTS", "").split(",")  # Multiple ports separated by commas

logger.debug(f"Environment variables: {dict(os.environ)}")
logger.debug(f"Proxy configuration: Hosts={proxy_hosts}, Ports={proxy_ports}, Username={'Present' if username else 'Missing'}, Password={'Present' if password else 'Missing'}")

proxy_configs = []

def create_proxy_url(host: str, port: str) -> str:
    """Create a proxy URL with the given host and port."""
    return f"http://{username}:{password}@{host.strip()}:{port.strip()}"

def get_random_proxy() -> dict:
    """Get a random proxy configuration from the available proxies."""
    if not proxy_configs:
        return None
    return random.choice(proxy_configs)

if username and password and proxy_hosts and proxy_ports:
    logger.debug("Configuring Webshare proxies")
    
    # Create proxy configurations for each host-port pair
    for host, port in zip(proxy_hosts, proxy_ports):
        if not host.strip() or not port.strip():
            continue
            
        proxy_url = create_proxy_url(host, port)
        proxy_config = {
            "http": proxy_url,
            "https": proxy_url
        }
        proxy_configs.append(proxy_config)
    
    if proxy_configs:
        # Configure proxy for YouTubeTranscriptApi with the first proxy (will be rotated later)
        YouTubeTranscriptApi.proxies = proxy_configs[0]
        
        logger.debug("Proxy configuration complete")
        logger.debug(f"Number of proxy configurations: {len(proxy_configs)}")
        
        # Test each proxy configuration
        for i, proxy_config in enumerate(proxy_configs):
            try:
                # Use a test URL that's less likely to be blocked
                test_response = requests.get(
                    "http://ip-api.com/json",
                    proxies=proxy_config,
                    timeout=10
                )
                proxy_url = urlparse(proxy_config["http"]).netloc.split("@")[1]
                logger.debug(f"Proxy {i+1} ({proxy_url}) test response: {test_response.text}")
            except Exception as e:
                logger.error(f"Proxy {i+1} test failed: {str(e)}")
else:
    logger.warning("Webshare proxy credentials not found")
    logger.debug("Environment variables available: " + ", ".join(os.environ.keys()))

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
        "proxy_count": len(proxy_configs)
    }

@app.get("/transcript/{video_id}")
async def get_transcript(
    video_id: str, 
    language: Optional[str] = None,
    format: Optional[Literal["text", "vtt", "srt", "json"]] = None,
    preserve_formatting: bool = False
):
    try:
        logger.debug(f"Fetching transcript for video {video_id} with language {language}, format {format}")
        
        # Try each proxy until successful or all fail
        last_error = None
        for attempt in range(len(proxy_configs)):
            try:
                proxy_config = get_random_proxy()
                if not proxy_config:
                    raise Exception("No proxy configurations available")
                
                YouTubeTranscriptApi.proxies = proxy_config
                proxy_url = urlparse(proxy_config["http"]).netloc.split("@")[1]
                logger.debug(f"Attempt {attempt + 1} using proxy {proxy_url}")
                
                # First try to get the transcript in the requested language
                if language:
                    logger.debug(f"Attempting to fetch transcript in {language}")
                    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[language])
                else:
                    logger.debug("Attempting to fetch transcript in English")
                    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
                
                # If we get here, the request was successful
                break
                
            except Exception as e:
                last_error = e
                logger.debug(f"Attempt {attempt + 1} failed: {str(e)}")
                continue
        else:
            # All attempts failed
            raise last_error if last_error else Exception("All proxy attempts failed")
            
        logger.debug(f"Successfully fetched transcript with {len(transcript)} segments")
        
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
        elif "YouTube is blocking requests from your IP" in error_message:
            status_code = 503
            detail = "Service temporarily unavailable. Please try again later."
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
        logger.debug(f"Listing languages for video {video_id}")
        
        # Try each proxy until successful or all fail
        last_error = None
        for attempt in range(len(proxy_configs)):
            try:
                proxy_config = get_random_proxy()
                if not proxy_config:
                    raise Exception("No proxy configurations available")
                
                YouTubeTranscriptApi.proxies = proxy_config
                proxy_url = urlparse(proxy_config["http"]).netloc.split("@")[1]
                logger.debug(f"Attempt {attempt + 1} using proxy {proxy_url}")
                
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                
                # If we get here, the request was successful
                break
                
            except Exception as e:
                last_error = e
                logger.debug(f"Attempt {attempt + 1} failed: {str(e)}")
                continue
        else:
            # All attempts failed
            raise last_error if last_error else Exception("All proxy attempts failed")
        
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
        error_message = str(e)
        logger.error(f"Error listing languages: {error_message}")
        
        if "Video unavailable" in error_message:
            status_code = 404
            detail = "The video is unavailable or does not exist."
        elif "YouTube is blocking requests from your IP" in error_message:
            status_code = 503
            detail = "Service temporarily unavailable. Please try again later."
        else:
            status_code = 500
            detail = f"An error occurred while fetching available languages: {error_message}"
            
        raise HTTPException(
            status_code=status_code,
            detail=detail
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port) 