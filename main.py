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
import random
import time
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

def validate_env_vars():
    """Validate required environment variables are present and properly formatted."""
    required_vars = {
        "WEBSHARE_PROXY_HOSTS": os.getenv("WEBSHARE_PROXY_HOSTS"),
        "WEBSHARE_PROXY_PORTS": os.getenv("WEBSHARE_PROXY_PORTS"),
        "WEBSHARE_PROXY_USERNAMES": os.getenv("WEBSHARE_PROXY_USERNAMES"),
        "WEBSHARE_PROXY_PASSWORD": os.getenv("WEBSHARE_PROXY_PASSWORD")
    }
    
    missing_vars = [k for k, v in required_vars.items() if not v]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
        
    # Validate that lists have matching lengths
    hosts = required_vars["WEBSHARE_PROXY_HOSTS"].split(",")
    ports = required_vars["WEBSHARE_PROXY_PORTS"].split(",")
    usernames = required_vars["WEBSHARE_PROXY_USERNAMES"].split(",")
    
    if not (len(hosts) == len(ports) == len(usernames)):
        logger.error("Mismatch in number of hosts, ports, and usernames")
        return False
        
    return True

# Configure proxy at module level
if not validate_env_vars():
    logger.error("Environment validation failed. Service may not work properly.")
else:
    proxy_hosts = os.getenv("WEBSHARE_PROXY_HOSTS", "").split(",")
    proxy_ports = os.getenv("WEBSHARE_PROXY_PORTS", "").split(",")
    proxy_usernames = os.getenv("WEBSHARE_PROXY_USERNAMES", "").split(",")
    proxy_password = os.getenv("WEBSHARE_PROXY_PASSWORD")

# Rate limiting configuration
MIN_REQUEST_INTERVAL = 2  # Minimum seconds between requests to the same proxy
last_proxy_use = {}  # Track when each proxy was last used

logger.debug(f"Environment variables: {dict(os.environ)}")
logger.debug(f"Proxy configuration: Hosts={proxy_hosts}, Ports={proxy_ports}, Usernames={proxy_usernames}, Password={'Present' if proxy_password else 'Missing'}")

proxy_configs = []

def create_proxy_url(host: str, port: str, username: str) -> str:
    """Create a proxy URL with the given host, port, and username."""
    return f"http://{username}:{proxy_password}@{host.strip()}:{port.strip()}"

def get_random_proxy() -> dict:
    """Get a random proxy configuration from the available proxies, respecting rate limits."""
    if not proxy_configs:
        logger.error("No proxy configurations available!")
        return None
        
    current_time = time.time()
    
    # Sort proxies by last use time to prefer least recently used
    available_proxies = sorted(
        proxy_configs,
        key=lambda p: last_proxy_use.get(p["http"], 0)
    )
    
    # Find first proxy that's not rate limited
    for proxy in available_proxies:
        if current_time - last_proxy_use.get(proxy["http"], 0) >= MIN_REQUEST_INTERVAL:
            return proxy
            
    # If all proxies are rate-limited, wait for the one that will be available soonest
    next_available = min(last_proxy_use.values()) + MIN_REQUEST_INTERVAL
    wait_time = next_available - current_time
    if wait_time > 0:
        logger.debug(f"All proxies rate limited, waiting {wait_time:.2f} seconds")
        time.sleep(wait_time)
        return available_proxies[0]
    
    return available_proxies[0]

def test_proxy(proxy_config: dict, username: str, proxy_url: str) -> bool:
    """Test a proxy configuration and return True if it's working."""
    try:
        # First test with ip-api.com
        test_response = requests.get(
            "http://ip-api.com/json",
            proxies=proxy_config,
            timeout=10
        )
        if test_response.status_code != 200 or "forbidden" in test_response.text.lower():
            logger.error(f"Proxy {username}@{proxy_url} failed basic connectivity test")
            return False
            
        logger.debug(f"Proxy {username}@{proxy_url} passed basic test: {test_response.text}")
        
        # Then test with YouTube
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }
        youtube_response = requests.get(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            proxies=proxy_config,
            headers=headers,
            timeout=10
        )
        if youtube_response.status_code == 429:
            logger.warning(f"Proxy {username}@{proxy_url} rate limited by YouTube")
            return True  # Still consider it valid, we'll handle rate limiting separately
        elif youtube_response.status_code != 200:
            logger.error(f"Proxy {username}@{proxy_url} failed YouTube connectivity test")
            return False
            
        logger.debug(f"Proxy {username}@{proxy_url} passed YouTube test")
        return True
        
    except Exception as e:
        logger.error(f"Proxy {username}@{proxy_url} test failed with error: {str(e)}")
        return False

def update_proxy_last_use(proxy_config: dict):
    """Update the last use time for a proxy."""
    last_proxy_use[proxy_config["http"]] = time.time()

if proxy_hosts and proxy_ports and proxy_usernames and proxy_password:
    logger.debug("Configuring Webshare proxies")
    
    # Create proxy configurations for each host-port-username combination
    for host, port, username in zip(proxy_hosts, proxy_ports, proxy_usernames):
        if not host.strip() or not port.strip() or not username.strip():
            continue
            
        proxy_url = create_proxy_url(host, port, username)
        proxy_config = {
            "http": proxy_url,
            "https": proxy_url
        }
        
        # Test the proxy before adding it
        proxy_netloc = f"{host.strip()}:{port.strip()}"
        if test_proxy(proxy_config, username, proxy_netloc):
            proxy_configs.append(proxy_config)
            last_proxy_use[proxy_url] = 0  # Initialize last use time
            logger.debug(f"Added working proxy: {username}@{proxy_netloc}")
    
    if proxy_configs:
        # Configure proxy for YouTubeTranscriptApi with the first proxy (will be rotated later)
        YouTubeTranscriptApi.proxies = proxy_configs[0]
        
        logger.debug("Proxy configuration complete")
        logger.debug(f"Number of working proxy configurations: {len(proxy_configs)}")
    else:
        logger.error("No working proxies found!")
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
        if not proxy_configs:
            raise HTTPException(
                status_code=503,
                detail="No proxy configurations available. Service is temporarily unavailable."
            )
            
        logger.debug(f"Fetching transcript for video {video_id} with language {language}, format {format}")
        
        # Try each proxy until successful or all fail
        last_error = None
        used_proxies = set()
        max_retries = min(len(proxy_configs) * 2, 10)  # Cap at 10 retries
        retry_count = 0
        backoff_time = 1  # Start with 1 second backoff
        
        while retry_count < max_retries and len(used_proxies) < len(proxy_configs):
            try:
                proxy_config = get_random_proxy()
                if not proxy_config:
                    raise Exception("No proxy configurations available")
                
                proxy_url = urlparse(proxy_config["http"]).netloc.split("@")[1]
                proxy_id = f"{urlparse(proxy_config['http']).username}@{proxy_url}"
                
                if proxy_id in used_proxies:
                    time.sleep(backoff_time)
                    backoff_time = min(backoff_time * 2, 30)  # Exponential backoff, max 30 seconds
                    continue
                    
                used_proxies.add(proxy_id)
                retry_count += 1
                
                YouTubeTranscriptApi.proxies = proxy_config
                logger.debug(f"Attempt {retry_count} using proxy {proxy_id}")
                
                update_proxy_last_use(proxy_config)
                
                # First try to get the transcript in the requested language
                if language:
                    logger.debug(f"Attempting to fetch transcript in {language}")
                    transcript = YouTubeTranscriptApi().fetch(
                        video_id, 
                        languages=[language],
                        preserve_formatting=preserve_formatting
                    )
                else:
                    logger.debug("Attempting to fetch transcript in English")
                    transcript = YouTubeTranscriptApi().fetch(
                        video_id, 
                        languages=['en'],
                        preserve_formatting=preserve_formatting
                    )
                
                # If we get here, the request was successful
                logger.debug(f"Successfully fetched transcript using proxy {proxy_id}")
                break
                
            except Exception as e:
                last_error = e
                error_str = str(e)
                logger.debug(f"Attempt with proxy {proxy_id} failed: {error_str}")
                
                if "429 Client Error: Too Many Requests" in error_str:
                    # If rate limited, wait longer before trying this proxy again
                    last_proxy_use[proxy_config["http"]] = time.time() + 30  # Wait at least 30 seconds
                    logger.warning(f"Proxy {proxy_id} rate limited, marking as unavailable for 30 seconds")
                
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
        elif "YouTube is blocking requests from your IP" in error_message or "429" in error_message:
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
        used_proxies = set()  # Keep track of which proxies we've tried
        max_retries = len(proxy_configs) * 2  # Allow each proxy to be tried twice
        retry_count = 0
        
        while retry_count < max_retries and len(used_proxies) < len(proxy_configs):
            try:
                proxy_config = get_random_proxy()
                if not proxy_config:
                    raise Exception("No proxy configurations available")
                
                # Get proxy identifier for logging and tracking
                proxy_url = urlparse(proxy_config["http"]).netloc.split("@")[1]
                proxy_id = f"{urlparse(proxy_config['http']).username}@{proxy_url}"
                
                # Skip if we've tried this proxy too recently
                if proxy_id in used_proxies and retry_count < len(proxy_configs):
                    continue
                    
                used_proxies.add(proxy_id)
                retry_count += 1
                
                YouTubeTranscriptApi.proxies = proxy_config
                logger.debug(f"Attempt {retry_count} using proxy {proxy_id}")
                
                # Update last use time for this proxy
                update_proxy_last_use(proxy_config)
                
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                
                # If we get here, the request was successful
                logger.debug(f"Successfully listed languages using proxy {proxy_id}")
                break
                
            except Exception as e:
                last_error = e
                error_str = str(e)
                logger.debug(f"Attempt with proxy {proxy_id} failed: {error_str}")
                
                if "429 Client Error: Too Many Requests" in error_str:
                    # If rate limited, wait longer before trying this proxy again
                    last_proxy_use[proxy_config["http"]] = time.time() + 30  # Wait at least 30 seconds
                    logger.warning(f"Proxy {proxy_id} rate limited, marking as unavailable for 30 seconds")
                
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
        if not proxy_configs:
            raise HTTPException(
                status_code=503,
                detail="No proxy configurations available. Service is temporarily unavailable."
            )
            
        logger.debug(f"Translating transcript for video {video_id} to {target_language}")
        
        # Try each proxy until successful or all fail
        last_error = None
        used_proxies = set()
        max_retries = min(len(proxy_configs) * 2, 10)
        retry_count = 0
        backoff_time = 1
        
        while retry_count < max_retries and len(used_proxies) < len(proxy_configs):
            try:
                proxy_config = get_random_proxy()
                if not proxy_config:
                    raise Exception("No proxy configurations available")
                
                proxy_url = urlparse(proxy_config["http"]).netloc.split("@")[1]
                proxy_id = f"{urlparse(proxy_config['http']).username}@{proxy_url}"
                
                if proxy_id in used_proxies:
                    time.sleep(backoff_time)
                    backoff_time = min(backoff_time * 2, 30)
                    continue
                    
                used_proxies.add(proxy_id)
                retry_count += 1
                
                YouTubeTranscriptApi.proxies = proxy_config
                logger.debug(f"Attempt {retry_count} using proxy {proxy_id}")
                
                update_proxy_last_use(proxy_config)
                
                # Get transcript list
                transcript_list = YouTubeTranscriptApi().list(video_id)
                
                # Find source transcript
                source_langs = [source_language] if source_language else ['en']
                transcript = transcript_list.find_transcript(source_langs)
                
                # Translate to target language
                translated = transcript.translate(target_language)
                transcript_data = translated.fetch()
                
                logger.debug(f"Successfully translated transcript using proxy {proxy_id}")
                
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
                last_error = e
                error_str = str(e)
                logger.debug(f"Attempt with proxy {proxy_id} failed: {error_str}")
                
                if "429 Client Error: Too Many Requests" in error_str:
                    last_proxy_use[proxy_config["http"]] = time.time() + 30
                    logger.warning(f"Proxy {proxy_id} rate limited, marking as unavailable for 30 seconds")
                
                continue
        else:
            # All attempts failed
            raise last_error if last_error else Exception("All proxy attempts failed")
            
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
            detail = "Service temporarily unavailable. Please try again later."
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