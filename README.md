# YouTube Transcript Service

A FastAPI service that fetches and formats YouTube video transcripts.

## Features

- Fetch transcripts from YouTube videos
- Support for multiple languages and translations
- Multiple output formats (Text, WebVTT, SRT, JSON)
- Proxy support to avoid IP blocking

## Setup

1. Clone the repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set up environment variables:
   - Copy `.env.example` to `.env`
   - Add your Webshare proxy credentials:
     ```
     WEBSHARE_PROXY_USERNAME=your_username_here
     WEBSHARE_PROXY_PASSWORD=your_password_here
     ```
   - (Optional) Set custom port:
     ```
     PORT=8001
     ```

## Running the Service

```bash
python main.py
```

The service will start on port 8001 by default.

## API Endpoints

### Get Transcript

```
GET /transcript/{video_id}
```

Query parameters:

- `language`: Language code (e.g., 'en', 'es', 'de')
- `format`: Output format ('text', 'vtt', 'srt', 'json')
- `preserve_formatting`: Boolean to preserve HTML formatting

### List Available Languages

```
GET /languages/{video_id}
```

Returns available transcripts and translation options for a video.

## Deployment

### Deploy to Render.com

1. Fork this repository
2. Create a new Web Service on Render.com
3. Connect your forked repository
4. Add environment variables:
   - `WEBSHARE_PROXY_USERNAME`: Your Webshare proxy username
   - `WEBSHARE_PROXY_PASSWORD`: Your Webshare proxy password
   - `PORT`: 10000 (Render's preferred port)

The service will be automatically deployed when you push changes to your repository.

### Using the Service

Once deployed, you can use the service by making requests to your Render.com URL:

```bash
# Get available languages
curl https://your-service.onrender.com/languages/VIDEO_ID

# Get transcript
curl https://your-service.onrender.com/transcript/VIDEO_ID?language=en&format=srt
```

## Proxy Configuration

This service uses Webshare proxy to avoid IP blocking by YouTube. To use it:

1. Sign up for a Webshare proxy account at https://www.webshare.io/
2. Get your proxy credentials
3. Add them to your environment variables

If no proxy credentials are provided, the service will attempt to make direct requests (may be blocked by YouTube).

## Error Handling

The service handles various error cases:

- Video unavailable
- No transcripts available
- Language not available
- IP blocking
- Network errors

## Development

Contributions are welcome! Please feel free to submit a Pull Request.
