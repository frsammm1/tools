# PDF & Video Editor Telegram Bot

Advanced Telegram bot for PDF manipulation and video thumbnail editing.

## Features

### PDF Tools
- Delete pages by image matching (SIFT algorithm)
- Text watermark with opacity control
- Insert pages at any position
- Find & replace text with common words suggestions
- Batch file renaming
- Thumbnail creation/removal

### Video Tools
- Batch thumbnail replacement
- Thumbnail with text watermark
- Multiple video processing

## Setup

1. Get bot token from [@BotFather](https://t.me/BotFather)
2. Get your user ID from [@userinfobot](https://t.me/userinfobot)
3. Set environment variables:
```bash
BOT_TOKEN=your_token
ALLOWED_USER_ID=your_user_id
```

## Deploy

### Render/Railway
```bash
docker build -t pdf-bot .
docker run -e BOT_TOKEN=xxx -e ALLOWED_USER_ID=xxx pdf-bot
```

## Usage
Send `/start` to bot and follow menu.

No login required. Only authorized user can access.