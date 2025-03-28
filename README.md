# VideoSage Transcript Service

A FastAPI service that fetches and formats YouTube video transcripts.

## Local Development

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run the service:

```bash
python main.py
```

The service will be available at `http://localhost:8001`.

## API Endpoints

- `GET /`: Health check endpoint
- `GET /transcript/{video_id}`: Get transcript for a YouTube video
  - Optional query parameter: `language` (e.g., 'en', 'es', 'fr')

## Deployment

This service can be deployed to Render.com:

1. Create a new account on Render.com
2. Connect your GitHub repository
3. Create a new Web Service
4. Use the following settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python main.py`
   - Environment Variables:
     - `PORT`: 8001

The service will be automatically deployed when you push changes to your repository.
