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
        # Configure language preferences
        languages = [language] if language else ['en']
        if 'en' not in languages:
            languages.append('en')  # Add English as fallback
        
        # Fetch transcript
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        try:
            # First try to get the transcript in the requested language
            transcript = transcript_list.find_transcript(languages)
        except:
            # If that fails, try to get any transcript and translate it
            try:
                transcript = transcript_list.find_transcript(['en'])
                if language and language != 'en':
                    transcript = transcript.translate(language)
            except:
                # If English isn't available, just get the first available transcript
                available_transcripts = list(transcript_list.transcript_data.keys())
                if not available_transcripts:
                    raise Exception("No transcripts available for this video")
                transcript = transcript_list.find_transcript([available_transcripts[0]])
                if language:
                    try:
                        transcript = transcript.translate(language)
                    except:
                        pass  # Keep original if translation fails
        
        # Fetch the actual transcript data
        transcript_data = transcript.fetch()
        
        # Format transcript with timestamps
        formatted_transcript = ""
        for snippet in transcript_data:
            # Access attributes using the new format
            start = float(snippet.start)
            text = snippet.text
            
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
        print(f"Error fetching transcript: {str(e)}")  # Debug logging
        raise HTTPException(
            status_code=404,
            detail=f"Could not retrieve transcript: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port) 