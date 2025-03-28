from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter, WebVTTFormatter, SRTFormatter, JSONFormatter
from youtube_transcript_api._transcripts import TranscriptList
from youtube_transcript_api.formatters import Formatter
from youtube_transcript_api.proxies import WebshareProxyConfig
from typing import Optional, Literal
import os
from dotenv import load_dotenv
import logging
import requests

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="YouTube Transcript Service")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_proxy_config() -> Optional[dict]:
    """Initialize proxy configuration with Webshare credentials."""
    username = os.getenv("WEBSHARE_PROXY_USERNAME")
    password = os.getenv("WEBSHARE_PROXY_PASSWORD")
    
    if not username or not password:
        logger.warning("Webshare proxy credentials not found")
        return None
        
    logger.debug("Initializing Webshare proxy configuration")
    proxy_url = f"http://{username}:{password}@p.webshare.io:80/"
    return {
        "http": proxy_url,
        "https": proxy_url
    }

@app.get("/")
async def root():
    return {"status": "ok", "service": "YouTube Transcript Service"}

@app.get("/transcript/{video_id}")
async def get_transcript(
    video_id: str, 
    language: Optional[str] = None,
    format: Optional[Literal["text", "vtt", "srt", "json"]] = None,
    preserve_formatting: bool = False
):
    try:
        logger.debug(f"Fetching transcript for video {video_id} with language {language}, format {format}")
        
        # Configure proxy
        proxy_config = get_proxy_config()
        if proxy_config:
            logger.debug("Using Webshare proxy for requests")
            YouTubeTranscriptApi.proxies = proxy_config
            # Also configure requests library to use the same proxy
            os.environ['HTTP_PROXY'] = proxy_config['http']
            os.environ['HTTPS_PROXY'] = proxy_config['https']
        else:
            logger.warning("No proxy configuration available, requests may be blocked")
        
        try:
            # First try to get the transcript in the requested language
            if language:
                logger.debug(f"Attempting to fetch transcript in {language}")
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[language])
            else:
                logger.debug("Attempting to fetch transcript in English")
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        except Exception as e:
            logger.debug(f"Initial fetch attempt failed: {str(e)}")
            if language:
                # If specific language fails, try English
                try:
                    logger.debug("Falling back to English")
                    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
                    # Try to translate if needed
                    if language != 'en':
                        logger.debug(f"Attempting to translate to {language}")
                        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                        en_transcript = transcript_list.find_transcript(['en'])
                        transcript = en_transcript.translate(language).fetch()
                except Exception as e2:
                    logger.debug(f"English fallback failed: {str(e2)}")
                    # If English fails, try any available language
                    logger.debug("Trying any available language")
                    transcript = YouTubeTranscriptApi.get_transcript(video_id)
            else:
                # If no specific language was requested, try any available language
                logger.debug("No language specified, trying any available")
                transcript = YouTubeTranscriptApi.get_transcript(video_id)
        
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
        
        # Configure proxy
        proxy_config = get_proxy_config()
        if proxy_config:
            logger.debug("Using Webshare proxy for requests")
            YouTubeTranscriptApi.proxies = proxy_config
        else:
            logger.warning("No proxy configuration available, requests may be blocked")
            
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
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
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port) 