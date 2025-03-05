## How the Bot Works

The Subtitles Generator bot operates through a series of steps to download, transcribe, and process video subtitles. Here is an overview of how the bot works:

1. **User Interaction via Telegram**:

   - Users interact with the bot through Telegram, sending commands and receiving updates.
   - The bot provides options for downloading videos, transcribing them, and generating subtitles.

2. **Downloading Videos**:

   - The bot uses `yt_dlp` to download videos from various platforms.
   - Users can customize download options such as video quality and format.
   - Real-time progress updates are provided during the download process.

3. **Transcribing Videos**:

   - Once a video is downloaded, the bot transcribes the audio to generate subtitles.
   - The transcription process uses a specified model (e.g., `victor-upmeet/whisperx`) and version.
   - Users can set limits on the duration of transcription.

4. **Generating Subtitles**:

   - The bot generates subtitles from the transcribed text.
   - Users have the option to bake subtitles directly into the video or display them on a website.

5. **Integration with AWS S3**:

   - The bot can upload videos and subtitles to an AWS S3 bucket.
   - Environment variables are used to configure AWS access keys, region, and bucket name.

6. **CloudFront Integration**:

   - The bot can generate URLs for accessing files through AWS CloudFront.
   - Environment variables are used to configure the CloudFront path.

7. **Email Notifications**:

   - The bot can send email notifications using the configured email provider.
   - Environment variables are used to configure email account details and server settings.

8. **Payment Integration**:

   - The bot supports payment processing through Telegram's payment provider.
   - Environment variables are used to configure the payment provider token.

9. **Running the Bot**:

   - Before running the bot, ensure the `telegram-bot-api` server is running locally.
   - Start the bot using the command `python3 bot.py`.

10. **Configuration**:
    - Key configurations such as download options and paths are set in the `download.py` file.
    - The bot token and other environment variables are set before running the bot.

This comprehensive setup allows users to efficiently download, transcribe, and process video subtitles through a user-friendly Telegram bot interface.

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/awerks/subtitles.git
   cd subtitles
   ```

2. Create a virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Set environment variables for `api_id` and `api_hash`:

````bash
Set the following environment variables before running the bot:

```bash
export apiid=<api_id>  # Your Telegram API ID
export apihash=<api_hash>  # Your Telegram API hash
export AWS_ACCESS_KEY_ID=<AWS ACCESS KEY ID>  # AWS access key ID for S3
export AWS_DEFAULT_REGION=<AWS DEFAULT REGION>  # AWS region for S3
export AWS_SECRET_ACCESS_KEY=<AWS SECRET ACCESS KEY>  # AWS secret access key for S3
export bucketname=<S3 BUCKET NAME>  # S3 bucket name for storing files
export BURN_LIMIT_MIN=<BURN LIMIT MIN>  # Limit for burning subtitles in minutes
export CLOUDFRONT_PATH=<CLOUDFRONT HTTPS PATH>  # CloudFront path for accessing files
export DATABASE_URL=<DATABASE PRIVATE URL>  # Private database URL, used in production
export DATABASE_PUBLIC_URL=<DATABASE PUBLIC URL>  # Public database URL, used in local development
export deeplapi=<DEEPL API KEY>  # DeepL API key for translations
export DEFAULT_AVAILABLE_MINUTES=60  # Default available minutes for transcription
export EMAIL_PASSWORD=<EMAIL PASSWORD>  # Email account password
export EMAIL_PORT=<EMAIL PORT>  # Email server port
export EMAIL_PROVIDER=<EMAIL PROVIDER>  # Email service provider
export EMAIL_USERNAME=<EMAIL USERNAME>  # Email account username
export ENDPOINT=<ADD VIDEO PAGE HTTPS ENDPOINT>  # Endpoint for adding video page
export PAYMENT_PROVIDER_TOKEN=<TELEGRAM PAYMENT PROVIDER TOKEN>  # Telegram payment provider token
export REPLICATE_API_TOKEN=<REPLICATE_API_TOKEN>  # Replicate API token
export RESULT_PATH=<RESULT HTTPS PATH>  # Path for accessing results
export TOKEN=<TOKEN>  # Bot token
export TRANSCRIPTION_LIMIT_MIN=120  # Transcription limit in minutes
export MODEL_NAME=victor-upmeet/whisperx  # Model name for transcription
export MODEL_VERSION=84d2ad2d6194fe98a17d2b60bef1c7f910c46b2f6fd38996ca457afd9c8abfcb  # Model version for transcription
````

Before running the bot, ensure you have the `telegram-bot-api` server running. If you don't have it installed,
you can compile the telegram-bot-api from source with instructions from [telegram-bot-api](https://tdlib.github.io/telegram-bot-api/build.html)

place the `telegram-bot-api` folder with telegram-bot-api binary in the root directory of the project.

The reason for using a local telegram server is the ability to send large files (up to 2GB) compared to the official telegram server which has a limit of 50MB.

Start the local telegram server:

```bash
./telegram-bot-api/telegram-bot-api --api-id $api_id --api-hash $apihash --local
```

you can compile the telegram-bot-api from source with instructions from [telegram-bot-api](https://tdlib.github.io/telegram-bot-api/build.html)

Download these fonts for ffmpeg (optional):

```markdown
- Benguiat Bold.otf
- Josefin Sans Bold.otf
- Montserrat-Bold.otf
- NotoNastaliqUrdu-SemiBold.ttf
- NotoSansArabic-SemiBold.ttf
- NotoSans.JP-SemiBold.ttf
- NotoSansKR-Medium.otf
- NotoSansSC-Medium.otf
- OpenSans-Bold.otf
- ProbaPro-Bold.otf
- Roboto-Medium.otf
- TheBoldFont-Bold.otf
- TrebuchetMS-Bold.otf
- WorkSans-Bold.otf
```

Run the bot:

```bash
python3 bot.py
```

## Configuration

Change your watermark in `watermark` folder

in production, set environment variable `production` to 1

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request on GitHub.

## Contact

For any questions or support, please contact [support@captionyx.com](mailto:support@captionyx.com).

## Acknowledgments

- [yt-dlp]("https://github.com/yt-dlp/yt-dlp")
- [WhisperX]("https://github.com/m-bain/whisperX")
- [FFmpeg](https://ffmpeg.org/)
- [python-telegram-bot](https://python-telegram-bot.org/)
- [telegram-bot-api](https://tdlib.github.io/telegram-bot-api/)
- [Plyr](https://plyr.io/)
- Asynchronous S3
