from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="YouTube Transcript Service")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "service": "YouTube Transcript Service"}

@app.get("/transcript/{video_id}")
async def get_transcript(video_id: str, language: Optional[str] = None):
    try:
        # Initialize the API
        ytt_api = YouTubeTranscriptApi()
        
        try:
            # First try to fetch with the requested language
            if language:
                transcript = ytt_api.fetch(video_id, languages=[language])
            else:
                transcript = ytt_api.fetch(video_id, languages=['en'])
        except Exception as e:
            if language:
                # If specific language fails, try English
                try:
                    transcript = ytt_api.fetch(video_id, languages=['en'])
                    # Try to translate if needed
                    if language != 'en':
                        transcript = ytt_api.translate_transcript(transcript, language)
                except:
                    # If English fails, try any available language
                    transcript = ytt_api.fetch(video_id)
                    if language != transcript.language_code:
                        try:
                            transcript = ytt_api.translate_transcript(transcript, language)
                        except:
                            pass  # Keep original if translation fails
            else:
                # If no specific language was requested, try any available language
                transcript = ytt_api.fetch(video_id)
        
        # Format transcript with timestamps
        formatted_transcript = ""
        for snippet in transcript.snippets:
            start = float(snippet.start)
            text = snippet.text.strip()
            
            minutes = int(start // 60)
            seconds = int(start % 60)
            timestamp = f"{minutes}:{seconds:02d}"
            formatted_transcript += f"{timestamp} - {text}\n"
        
        return {
            "text": formatted_transcript.strip(),
            "source": "youtube_transcript_api",
            "language": transcript.language,
            "language_code": transcript.language_code,
            "is_generated": transcript.is_generated,
            "video_id": video_id
        }
        
    except Exception as e:
        error_message = str(e)
        print(f"Error fetching transcript: {error_message}")  # Debug logging
        
        if "Subtitles are disabled" in error_message:
            status_code = 404
            detail = "This video does not have subtitles or transcripts available."
        elif "Could not find transcript" in error_message:
            status_code = 404
            detail = f"No transcript available in the requested language: {language}"
        else:
            status_code = 500
            detail = "An error occurred while fetching the transcript"
            
        raise HTTPException(
            status_code=status_code,
            detail=detail
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port) 