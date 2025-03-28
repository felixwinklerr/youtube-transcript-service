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

## Proxy Configuration

This service uses Webshare proxy to avoid IP blocking by YouTube. To use it:

1. Sign up for a Webshare proxy account at https://www.webshare.io/
2. Get your proxy credentials
3. Add them to your `.env` file

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
