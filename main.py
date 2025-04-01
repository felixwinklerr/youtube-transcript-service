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
    
    # Configure proxy for YouTubeTranscriptApi
    YouTubeTranscriptApi.proxies = proxy_config
    logger.debug("Proxy configuration complete")

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
        
        try:
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
            logger.error(f"Error fetching transcript: {error_str}")
            
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
            detail = "Service temporarily unavailable due to rate limiting. Please try again later."
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
        
        # Try each proxy until successful or all fail
        last_error = None
        used_proxies = set()
        max_retries = min(len(proxy_config) * 2, 10)
        retry_count = 0
        backoff_time = 1
        
        while retry_count < max_retries and len(used_proxies) < len(proxy_config):
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