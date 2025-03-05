import shutil
import boto3
import math
import gc
import re
import replicate
import traceback
import aiohttp
import asyncio
import os
import logging
import deepl
import threading
from typing import Iterator
from persistent import Persistent
from datetime import datetime, time
from ffmpeg import FfmpegProgress, get_video_duration, get_video_resolution, get_audio, get_font_size
from subtitles import SubtitlesProcessor
from botocore.exceptions import NoCredentialsError
from constants import (
    LANGUAGE_CODES,
    FLAG_CODES,
    TELEGRAM_MESSAGE_LENGTH_LIMIT,
    TO_KEEP_WARM,
    BAR_WIDTH,
    PROGRESS_BAR_STYLE,
)
from s3 import AsynchronousS3
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessageEntity,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    CallbackContext,
    ConversationHandler,
    PreCheckoutQueryHandler,
)
from utils import (
    generate_random_string,
    language_to_flag,
    progress_function,
    make_url_friendly_datetime,
)
from handlers import (
    start,
    style,
    style_font_choice,
    style_fontsize_choice,
    style_border_style_choice,
    list_websites,
    help_command,
    bot_language,
    bot_language_choice,
    resolution,
    resolution_choice,
    transcribe_command,
    handle_transcribe_command,
    translateto,
    language_command_choice,
    subtitle,
    subtitle_choice_handler,
    show_available_minutes,
    handle_minutes_selection,
    reset_settings,
    select_minutes_command,
    precheckout_callback,
    successful_payment_callback,
    support_command,
)
from download import download_video
import yt_dlp
from pathlib import Path


persistent = Persistent()

(LINK, RESOLUTION, ORIGINAL_LANGUAGE, TRANSLATION_LANGUAGE, BURN_OR_DISPLAY, FONT, FONTSIZE, BORDERSTYLE) = range(8)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("deepl").setLevel(logging.WARNING)

TOKEN = os.getenv("TOKEN")
DEEPL_API_KEY = os.getenv("deeplapi")
BUCKETNAME = os.getenv("bucketname")
VERSION = os.getenv("version")
CLOUDFRONT_PATH = os.getenv("CLOUDFRONT_PATH")
ENDPOINT = os.getenv("ENDPOINT")
RESULT_PATH = os.getenv("RESULT_PATH")
MODEL_NAME = os.getenv("MODEL_NAME")
MODEL_VERSION = os.getenv("MODEL_VERSION")
FLASK_API_TOKEN = os.getenv("FLASK_API_TOKEN")

TRANSCRIPTION_LIMIT_MIN = int(os.getenv("TRANSCRIPTION_LIMIT_MIN"))

DEFAULT_AVAILABLE_MINUTES = int(os.getenv("DEFAULT_AVAILABLE_MINUTES"))


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get("running_task"):
        return ConversationHandler.END

    link = context.user_data["link"] = update.message.text
    persistent.check_settings(update, context)

    context.user_data["document"] = False

    user_id = context.user_data["user_id"]

    persistent.logger.info(
        f"{context.user_data['name']} (id: {user_id}; username: {context.user_data['username']}) has initalized a conversation."
    )
    persistent.logger.info(f"Link: {context.user_data['link']}")

    context.user_data["video_path"] = os.path.join(user_id, "video.mp4")

    if ("youtube.com" in link or "youtu.be" in link) and "playlist" in link:
        await update.message.reply_text(persistent.get_translation(context, "playlists_are_not_allowed"))
        return ConversationHandler.END

    if context.user_data.get("user_resolution") == "highest" or context.user_data.get("transcribe") == "yes":
        try:
            with yt_dlp.YoutubeDL({"noplaylist": True, "noprogress": True, "quiet": True}) as ydl:
                info_dict = ydl.extract_info(link, download=False)
                file_length = info_dict.get("duration_string")
                file_length_min = None
                if file_length:
                    file_length_min = int(
                        round(sum(int(t) * 60**i for i, t in enumerate(reversed(file_length.split(":"))))) / 60
                    )
                    persistent.logger.info(f"Video duration: {file_length_min} minutes")
                context.user_data["video_duration"] = file_length_min
        except Exception as e:
            logging.error(f"Error occurred in select_resolution: {str(e)}")
            traceback.print_exc()
            if "unavailable" in str(e):
                await update.message.reply_text(persistent.get_translation(context, "unavailable_video"))
            else:
                await update.message.reply_text(persistent.get_translation(context, "error_resolution_selection"))
            return ConversationHandler.END

        await select_language(update, context, original_language=True)
        return ORIGINAL_LANGUAGE

    else:
        try:
            await select_resolution(update, context, link)
            return RESOLUTION
        except Exception as e:
            logging.error(f"Error occurred in select_resolution: {str(e)}")
            traceback.print_exc()
            if "unavailable" in str(e):
                await update.message.reply_text(persistent.get_translation(context, "unavailable_video"))
            else:
                await update.message.reply_text(persistent.get_translation(context, "error_resolution_selection"))
            return ConversationHandler.END


async def handle_original_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query

    original_language = query.data.lower()
    await query.answer()
    context.user_data["original_language"] = original_language
    persistent.logger.info(f"{context.user_data['name']} selected {original_language} as original language.")
    if context.user_data["default_language"] != "default":
        return await handle_language(context.user_data["default_language"], context)
    else:
        await select_language(update, context)
        return TRANSLATION_LANGUAGE


async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id=0) -> int:
    try:
        nores = chat_id > 0
        message = None
        if isinstance(update, Update):
            query = update.callback_query

            deepl_code = query.data
            context.user_data["need_to_send_message"] = False
            await query.answer()
            message = context.user_data["message"]

        else:
            if nores:
                context.user_data["need_to_send_message"] = True
            else:
                message = context.user_data["message"]
                context.user_data["need_to_send_message"] = False
            deepl_code = update

        context.user_data["selected_language"] = deepl_code
        if context.user_data.get("transcribe") != "yes":
            subtitle_user_choice = context.user_data.get("subtitle_choice", "default")
            if subtitle_user_choice == "default":
                keyboard = [
                    [
                        InlineKeyboardButton(
                            persistent.get_translation(context, "burn_into_video_prompt"), callback_data="burn"
                        ),
                        InlineKeyboardButton(
                            persistent.get_translation(context, "display_website_prompt"),
                            callback_data="display",
                        ),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                if message:
                    await message.edit_text(
                        persistent.get_translation(context, "prompt_subtitle_choice_text"),
                        reply_markup=reply_markup,
                    )
                else:
                    context.user_data["message"] = await context.bot.send_message(
                        chat_id=context.user_data["chat_id"],
                        text=persistent.get_translation(context, "prompt_subtitle_choice_text"),
                        reply_markup=reply_markup,
                    )
                return BURN_OR_DISPLAY
            else:
                return await handle_burn_or_display(subtitle_user_choice, context)
        else:
            return await handle_burn_or_display("transcribe", context)

    except Exception as e:
        traceback.print_exc()

        await context.bot.send_message(
            chat_id=context.user_data["chat_id"], text=persistent.get_translation(context, "general_error")
        )

        return ConversationHandler.END


async def handle_burn_or_display(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if isinstance(update, Update):
            query = update.callback_query
            await query.answer()
            context.user_data["choice"] = query.data
        else:
            context.user_data["choice"] = update

        message = context.user_data.get("message")
        chat_id = context.user_data["chat_id"]
        video_duration = context.user_data.get("video_duration")

        persistent.logger.info(
            f"Video_duration: {video_duration}; Available minutes: {context.user_data['available_minutes']}"
        )

        if video_duration and video_duration > context.user_data["available_minutes"]:
            persistent.logger.info(f"{context.user_data['name']} requested a video longer than their minutes left!")

            """lang = context.user_data["bot_language"]

			base_text = (
				f"Oops! The video you've requested is longer than the minutes you have remaining ({context.user_data['available_minutes']} minutes). "
				"No worries—you can easily extend your time. Just use the /buy_minutes command to purchase additional minutes. 🛒\n\n"
				"Rest assured, your payment will be securely processed through Telegram's official payment system. "
				"Your credit card details remain confidential. 🛡️\n\n"
				"Want to learn more? Check out <a href='https://telegram.org/blog/payments?setln=en'>how Telegram's payment system works</a>."
			)"""

            text = f"{persistent.get_translation(context, 'limit_exceed_text')} ({context.user_data['available_minutes']} 🕒)\n\n{persistent.get_translation(context, 'limit_exceed_text_extra')}<a href='https://telegram.org/blog/payments?setln=en'>{persistent.get_translation(context, 'prompt_check_out_text')}</a>"

            if message:
                await message.edit_text(text, parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            return ConversationHandler.END

        loop = asyncio.get_running_loop()
        threading.Thread(target=run_in_thread, args=(loop, context)).start()

    except Exception as e:
        persistent.logger.info(f"An error occured: {e}")
        await message.reply_text(persistent.get_translation(context, "general_error"))

    finally:
        gc.collect()
        return ConversationHandler.END


def run_in_thread(loop, context):
    asyncio.run_coroutine_threadsafe(handle_video_operations(context), loop)


async def handle_video_operations(context):
    try:
        deepl_code = context.user_data.get("selected_language")
        message = context.user_data.get("message")
        chat_id = context.user_data["chat_id"]
        user_id = context.user_data["user_id"]
        isDocument = context.user_data.get("document")
        choice = context.user_data.get("choice")
        context.user_data["running_task"] = True
        video_duration = context.user_data.get("video_duration")
        need_to_check_video_duration = False

        if not video_duration:
            need_to_check_video_duration = True

        if isDocument:
            video_path = context.user_data.get("video_path")

        persistent.logger.info(f"{context.user_data['name']} selected language: {deepl_code}")

        transneed = False

        if not isDocument:
            persistent.logger.info("Downloading the video...")
            if message:
                await message.edit_text(persistent.get_translation(context, "downloading_video_text"))
            else:
                message = context.user_data["message"] = await context.bot.send_message(
                    chat_id=chat_id, text=persistent.get_translation(context, "downloading_video_text")
                )
            try:
                video_path = await download_video(context.user_data["link"], context)
                print("VIDEO PATH:", video_path)
                if need_to_check_video_duration:
                    persistent.logger.info("The video duration wasn't found. Checking again..")
                    context.user_data["video_duration"] = video_duration = get_video_duration(video_path)

                    if video_duration > context.user_data["available_minutes"]:
                        text = f"{persistent.get_translation(context, 'limit_exceed_text')} ({context.user_data['available_minutes']} 🕒)\n\n{persistent.get_translation(context, 'limit_exceed_text_extra')}<a href='https://telegram.org/blog/payments?setln=en'>{persistent.get_translation(context, 'prompt_check_out_text')}</a>"

                        await message.edit_text(text, parse_mode="HTML")
                        persistent.logger.info(
                            f"{context.user_data['name']} requested a video longer than available minutes."
                        )
                        return

            except Exception as e:
                await message.reply_text(persistent.get_translation(context, "error_downloading_video_text"))
                persistent.logger.info(f"Error downloading the video!\n{e}")
                traceback.print_exc()
                return

        # s3_thumbnail_path = f"{s3_base_path}thumbnails/"

        await message.edit_text(persistent.get_translation(context, "extracting_audio_text"))
        persistent.logger.info("Extracting audio...")

        audio_path, returncode = get_audio(video_path, message, context)
        if returncode == 1:
            await message.edit_text(persistent.get_translation(context, "no_audio_in_video_text"))
            persistent.logger.info("No audio in this video!")
            return

        context.user_data["task"] = "transcribe"
        if deepl_code == "EN-US":
            context.user_data["task"] = "translate"

        elif deepl_code != "Original":
            transneed = True
        to_transcribe = choice == "transcribe"
        try:
            persistent.logger.info("Generating subtitles/transcription...")
            if to_transcribe:
                await message.edit_text(persistent.get_translation(context, "generating_transcription_text"))
            else:
                await message.edit_text(persistent.get_translation(context, "generating_subtitles_text"))

            session = boto3.session.Session()
            (
                subtitles_or_transcription_path,
                detected_language,
            ) = await get_subtitles_or_transcription(audio_path, context, to_transcribe, message, session)

            if context.user_data["original_language"] == "detect":
                await message.edit_text(
                    f"{persistent.get_translation(context, 'detected_language_text')} {detected_language}"
                )

            upload_to_aws(
                subtitles_or_transcription_path,
                BUCKETNAME,
                context.user_data["s3_subtitles_path"],
                session,
            )

            if detected_language == deepl_code:
                # await message.edit_text(persistent.get_translation(context, "language_detected_text"))
                persistent.logger.info("Detected language is the chosen one.")
                transneed = False

        except Exception as e:
            await message.reply_text(persistent.get_translation(context, "error_generating_text"))
            traceback.print_exc()
            return

        length = context.user_data.get("length", 0)
        if length < 2:  # "Captioning by SubtitlesGeneratorBot" subtitle
            await message.edit_text(persistent.get_translation(context, "no_speech_detected_text"))
            return
        try:
            if transneed:
                persistent.logger.info("Translating subtitles/transcription...")
                if to_transcribe:
                    subtitles_or_transcription_path = await translate_transcription(
                        subtitles_or_transcription_path, deepl_code, context, message
                    )

        except Exception as e:
            await message.reply_text(persistent.get_translation(context, "error_translating_text"))
            traceback.print_exc()
            return

        if to_transcribe:
            if length < TELEGRAM_MESSAGE_LENGTH_LIMIT:
                with open(subtitles_or_transcription_path, "r", encoding="utf-8") as file:
                    text = file.read()
                    await message.edit_text(f"{persistent.get_translation(context, 'transcription_result_text')}{text}")
            else:
                await message.reply_document(
                    caption=persistent.get_translation(context, "transcription_result_text"),
                    document=subtitles_or_transcription_path,
                )
                await message.delete()
            await message.reply_text(persistent.get_translation(context, "prompt_for_new_transcription_text"))
            persistent.save_video(
                context.user_data.get("user_id"),
                context.user_data.get("username"),
                context.user_data.get("name"),
                "document" if isDocument else context.user_data.get("link"),
                context.user_data.get("video_duration"),
                "document" if isDocument else context.user_data.get("selected_resolution", "highest"),
                context.user_data.get("selected_language").lower(),
                True,
            )
            persistent.logger.info("Video saved succesfully.")
            gc.collect()

            context.user_data["available_minutes"] -= context.user_data["video_duration"]
            persistent.update_field(user_id, "available_minutes", context.user_data["available_minutes"])
            return

        if choice == "burn":
            out_path = subtitles_or_transcription_path.replace(".srt", "_edited.mp4")
            print("out_path", out_path)
            print("video_path", video_path)
            font_size = (
                context.user_data["user_font_size"]
                if context.user_data["user_font_size"] != "default"
                else context.user_data["font_size"] if "font_size" in context.user_data else get_font_size(video_path)
            )

            font_name = (
                context.user_data.get("user_font")
                if context.user_data.get("user_font") != "default"
                else "ProbaPro-Bold"
            )
            border_style = 4 if context.user_data.get("user_border_style") == "box" else 1

            """if border_style == 4:
				border_command = f"BorderStyle=4, BackColour=&H30000000, Shadow=0"
			else:
				border_command = f"BorderStyle=1, Outline=1.10"""

            if border_style == 4:
                # Outline=0.5
                border_command = f"BorderStyle=4,BackColour=&H30000000,Shadow=0"
            else:
                border_command = f"BorderStyle=1,Outline=1.10,Shadow=0.35"

            command = [
                "ffmpeg",
                "-vsync",
                "0",
                "-threads",
                "auto",
                "-i",
                f"{video_path}",
                "-i",
                "watermark/watermark2.png",
                "-filter_complex",
                f"[1:v]scale=iw*0.2:-1[logo];[0:v][logo]overlay=W-w-10:10,subtitles={subtitles_or_transcription_path}:force_style='FontName={font_name},FontSize={font_size},OutlineColour=&H20000000,Spacing=0.3,{border_command}'",
                "-c:a",
                "copy",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                out_path,
                "-y",
            ]
            print("command", command)
            try:
                last_update = 0
                update_threshold = (
                    1  # Set the threshold for the minimum change in progress required to trigger an update
                )
                persistent.logger.info("Adding subtitles...")
                (width, height) = get_video_resolution(video_path)

                for progress in run_ffmpeg_command(command):
                    if progress - last_update >= update_threshold:

                        bar = progress_function(0, 100, progress, BAR_WIDTH, progress_style=PROGRESS_BAR_STYLE)
                        await message.edit_text(
                            f"{persistent.get_translation(context, 'adding_subtitles_text')}<code>{bar} {progress}%</code>",
                            parse_mode="HTML",
                        )
                        last_update = progress
            except Exception as e:
                await message.reply_text(persistent.get_translation(context, "error_adding_subtitles_text"))
                traceback.print_exc()
                persistent.logger.info("Error while adding subtitles:")
                return

            try:
                persistent.logger.info("Saving the video...")

                persistent.save_video(
                    context.user_data.get("user_id"),
                    context.user_data.get("username"),
                    context.user_data.get("name"),
                    context.user_data.get("link"),
                    context.user_data.get("video_duration"),
                    context.user_data.get("selected_resolution", "document"),
                    context.user_data.get("selected_language").lower(),
                    False,
                )
                persistent.logger.info("Video saved succesfully.")

                await message.edit_text(persistent.get_translation(context, "sending_video_text"))

                await message.reply_chat_action("upload_video")

                await message.reply_video(
                    out_path,
                    supports_streaming=True,
                    height=height,
                    width=width,
                    duration=video_duration * 60,
                    write_timeout=1000,
                    connect_timeout=1000,
                    pool_timeout=1000,
                    read_timeout=1000,
                )

                await message.reply_document(
                    document=subtitles_or_transcription_path,
                    caption=persistent.get_translation(context, "here_are_your_subtitles_text"),
                )
                await message.reply_text(persistent.get_translation(context, "prompt_for_new_subtitle_text"))
                await message.delete()

                context.user_data["available_minutes"] -= context.user_data["video_duration"]
                persistent.update_field(user_id, "available_minutes", context.user_data["available_minutes"])

            except Exception as e:
                await message.reply_text(persistent.get_translation(context, "error_sending_video_text"))
                traceback.print_exc()
                persistent.logger.info("Error while saving/sending the video...")
                return

        elif choice == "display":
            if context.user_data.get("response_code") == 200:
                await check_request_completed(context, message)
                persistent.logger.info("Saving the video...")
                persistent.save_video(
                    user_id,
                    context.user_data.get("username"),
                    context.user_data.get("name"),
                    context.user_data.get("link"),
                    context.user_data.get("video_duration"),
                    context.user_data.get("selected_resolution", "document"),
                    context.user_data.get("selected_language").lower(),
                    False,
                )
                persistent.logger.info("Video saved succesfully.")

                context.user_data["available_minutes"] -= context.user_data["video_duration"]
                persistent.update_field(user_id, "available_minutes", context.user_data["available_minutes"])

                return ConversationHandler.END

            else:
                await context.bot.send_message(
                    chat_id=chat_id, text=persistent.get_translation(context, "error_generating_page_text")
                )
                return

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=persistent.get_translation(context, "general_error"))
        traceback.print_exc()
        return

    finally:
        context.user_data["running_task"] = False

        if os.path.exists(user_id):
            shutil.rmtree(user_id)

        gc.collect()

        if "message" in context.user_data:
            del context.user_data["message"]

        return


async def check_request_completed(context, message, isDisplay=True):
    while not context.user_data.get("video_request_completed", False):
        await asyncio.sleep(0.5)  # wait for 1 second before checking again

    # Once video_request_completed is True, execute the following code
    if isDisplay:
        await message.reply_text(
            f'<a href="{context.user_data["result_link"]}">{persistent.get_translation(context, "here_your_video")} {persistent.get_translation(context, "video")}</a>!\n\n{persistent.get_translation(context, "prompt_for_new_subtitle_text")}',
            parse_mode="HTML",
        )
        await context.user_data["message"].delete()

        persistent.logger.info("Generated a page succesfully.")


def on_success(file_size, duration, context):
    persistent.logger.info(f"A {file_size} bytes has been uploaded in {duration} secs.")
    context.user_data["video_request_completed"] = True


def on_failure(error):
    persistent.logger.info("An error occured: %s" % error)


def run_ffmpeg_command(cmd: list[str], dry: bool = False) -> Iterator[float]:
    ff = FfmpegProgress(cmd, dry_run=dry)
    yield from ff.run_command_with_progress()


async def get_subtitles_or_transcription(audio_path: str, context, to_transcribe, message, session):
    isDisplay = context.user_data.get("choice") == "display"

    task = context.user_data.get("task", "transcribe")
    text = (
        persistent.get_translation(context, "generating_transcription_text")
        if to_transcribe
        else persistent.get_translation(context, "generating_subtitles_text")
    )

    model = replicate.models.get(MODEL_NAME)
    version = model.versions.get(MODEL_VERSION)

    user_name = context.user_data["name"]
    user_id = context.user_data["user_id"]

    user_name_clean = re.sub(r"[^a-zA-Z0-9]", "-", user_name)

    path = os.path.join(
        user_id, "transcription.txt" if to_transcribe else "subtitles.vtt" if isDisplay else "subtitles.srt"
    )

    isDocument = context.user_data.get("document")

    currentTime = make_url_friendly_datetime()

    s3_base_path = os.path.join(f"{user_name_clean}-{user_id}", currentTime, "")
    s3_audio_path = os.path.join(s3_base_path, "audio.mp3")
    print("s3_audio_path", s3_audio_path)
    print("s3_base_path", s3_base_path)
    persistent.logger.info("Uploading audio...")

    upload_to_aws(audio_path, BUCKETNAME, s3_audio_path, session)

    original_language = (
        context.user_data["original_language"][:2] if context.user_data["original_language"] != "detect" else None
    )

    max_retries = 3  # Maximum number of retries
    retry_delay = 3  # Number of seconds to wait between retries
    print("language", original_language)
    for attempt in range(1, max_retries + 1):
        try:
            model_input = {
                "audio_file": os.path.join(CLOUDFRONT_PATH, s3_audio_path),
                "align_output": not to_transcribe,
            }
            if original_language:
                model_input.update({"language": original_language})

            prediction = replicate.predictions.create(version=version, input=model_input)
            break
        except Exception as e:
            persistent.logger.info(f"Error creating a prediction {e}")
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
            else:
                persistent.logger.info("Max retry attempts reached.")

    context.user_data["prediction"] = prediction
    duration = math.ceil(context.user_data.get("video_duration") * (1.1 if to_transcribe else 1.3)) + (
        7 if TO_KEEP_WARM else 600
    )
    i = 0
    # Keep looping until the prediction has succeeded
    last_progress = -1

    context.user_data["s3_subtitles_path"] = os.path.join(s3_base_path, "subtitles.srt")

    user_name = context.user_data["name"]

    user_id = context.user_data["user_id"]

    user_name_clean = re.sub(r"[^a-zA-Z0-9]", "-", user_name)

    context.user_data["s3_video_path"] = s3_video_path = os.path.join(s3_base_path, "video.mp4")

    context.user_data["s3_output_path"] = os.path.join(s3_base_path, "output.mp4")

    persistent.logger.info("Uploading a video...")
    context.user_data["video_request_completed"] = False
    if not isDisplay:
        persistent.logger.info(f"Video path: {os.path.join(CLOUDFRONT_PATH, s3_video_path)}")
        context.user_data["link"] = os.path.join(CLOUDFRONT_PATH, s3_video_path)

    s3 = AsynchronousS3(BUCKETNAME, session)

    s3.upload_file(context.user_data["video_path"], s3_video_path, on_success, on_failure, context)

    if isDisplay:

        context.user_data["s3_subtitles_path"] = s3_vtt_path = os.path.join(s3_base_path, "subtitles.vtt")

        language = context.user_data["selected_language"]

        file_name = generate_random_string(20)
        data = {
            "video_url": os.path.join(CLOUDFRONT_PATH, s3_video_path),
            "captions_url": os.path.join(CLOUDFRONT_PATH, s3_vtt_path),
            "original_video_url": context.user_data.get("link"),
            # "language_label": next(
            #     (key for key, val in LANGUAGE_CODES.items() if val == language),
            #     language,
            # ),
            "language": language.lower(),
            "file_name": file_name,
        }

        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": FLASK_API_TOKEN}

            async with session.post(ENDPOINT, json=data, headers=headers) as response:
                context.user_data["result_link"] = os.path.join(RESULT_PATH, file_name)
                context.user_data["response_code"] = response.status

    while True:
        prediction = replicate.predictions.get(prediction.id)

        if prediction.status == "succeeded":
            break
        elif prediction.status == "failed":
            await message.reply_text(persistent.get_translation(context, "prediction_fail_error"))
            raise Exception("Prediction failed")

        progress = int((i / duration) * 100)

        if i < duration and progress != last_progress:
            bar = progress_function(0, 100, progress, BAR_WIDTH, progress_style=PROGRESS_BAR_STYLE)
            await message.edit_text(f"{text}<code>{bar} {progress}%</code>", parse_mode="HTML")
            last_progress = progress

        await asyncio.sleep(0.5)

        i += 1

    # context.user_data["message"] = await message.edit_text(f"{text}<code>█████████████████ 100%</code>", parse_mode='HTML')

    output = prediction.output

    detected_language = output["detected_language"].upper()
    if detected_language == "EN":
        detected_language = "EN-US"

    elif detected_language == "PT":
        detected_language = "PT-PT"

    if to_transcribe:
        all_text_segments = [segment["text"] for segment in output["segments"]]
        transcription = " ".join(all_text_segments)
        with open(path, "w", encoding="utf-8") as file:
            file.write(transcription)
        context.user_data["length"] = len(transcription)

    else:
        advanced_splitting = context.user_data.get(
            "selected_language"
        ) == "Original" or detected_language == context.user_data.get("selected_language")
        # eng = task == "translate" and detected_language != "en"
        if advanced_splitting:
            # persistent.logger.info(f"advanced_splitting")
            word_segments = "word_segments" in output
            if word_segments:
                persistent.logger.info("advanced_splitting word segments")
                subtitles_proccessor = SubtitlesProcessor(
                    output["segments"],
                    detected_language.lower(),
                    max_line_length=60,
                    min_char_length_splitter=30,
                    is_vtt=isDisplay,
                )

            else:
                persistent.logger.info("language not supported but advanced_splitting spliiting")
                subtitles_proccessor = SubtitlesProcessor(
                    output["segments"],
                    detected_language.lower(),
                    max_line_length=60,
                    min_char_length_splitter=30,
                    is_vtt=isDisplay,
                )
                subtitles_proccessor.segments = subtitles_proccessor.process_segments(
                    advanced_splitting=False, normal_handling=False
                )

            context.user_data["length"] = subtitles_proccessor.save(path, advanced_splitting=True)
        else:
            normal_handling = task == "transcribe"
            word_segments = "word_segments" in output
            selected_language = context.user_data["selected_language"].lower()
            # persistent.logger.info(
            #     f"normal_handling: {normal_handling}, word_segments: {word_segments}, selected_language: {selected_language}"
            # )
            subtitles_proccessor = SubtitlesProcessor(
                output["segments"],
                selected_language,
                max_line_length=75,
                min_char_length_splitter=30,
                is_vtt=isDisplay,
            )
            subtitles_list = subtitles_proccessor.process_segments(
                advanced_splitting=False,
                normal_handling=normal_handling and word_segments,
            )
            # tamil - en-s. normal-handling - false, not-word_segments true. False or True = True
            # tamil - uk, normal-handling - true, not-word-segments true. True or True = True
            # English - uk, normal-handling - true, not word_segments - false. True or false = True
            #
            if len(subtitles_list) > 0:
                if normal_handling:
                    persistent.logger.info("normal_handling")
                    # if not word_segments:
                    # persistent.logger.info('translating subittles not supported align')
                    translated_text_list = await translate_subtitles(
                        [subtitle["text"] for subtitle in subtitles_list],
                        context.user_data["selected_language"],
                        context,
                        message,
                    )
                    translated_subtitles = []
                    for original, translated in zip(subtitles_list, translated_text_list):
                        translated_subtitles.append(
                            {
                                "start": original["start"],
                                "end": original["end"],
                                "text": translated.text,
                            }
                        )
                    subtitles_proccessor.segments = translated_subtitles
            context.user_data["length"] = subtitles_proccessor.save(path, advanced_splitting=True)

    del context.user_data["prediction"]

    persistent.logger.info(f"Detected language: {detected_language}.")

    return path, detected_language


async def translate_transcription(path, target_lang, context, message):
    translator = deepl.Translator(DEEPL_API_KEY)
    out_path = path.replace(".txt", "_translated.txt")
    await message.edit_text(persistent.get_translation(context, "translating_transcription_text"))
    with open(path, "rb") as in_file, open(out_path, "wb") as out_file:
        translator.translate_document(in_file, out_file, target_lang=target_lang)
    return out_path


async def translate_subtitles(sentences_to_translate, target_lang, context, message):
    translator = deepl.Translator(DEEPL_API_KEY)

    # Translate the concatenated text without splitting on newlines and preserving the format
    translated_sentences = translator.translate_text(
        sentences_to_translate,
        target_lang=target_lang,
        split_sentences="nonewlines",
        preserve_formatting=True,
    )

    return translated_sentences


async def select_resolution(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    with yt_dlp.YoutubeDL(
        {
            "noplaylist": True,
            "noprogress": True,
            "quiet": True,
        }
    ) as ydl:
        info_dict = ydl.extract_info(url, download=False)
        isYoutube = "youtube" in url or "youtu.be" in url
        resolutions_and_sizes = {}
        file_length = info_dict.get("duration_string")
        file_length_min = None
        if file_length:
            file_h_m_s = file_length.split(":")
            file_h_m_s = [int(sub_length) for sub_length in file_h_m_s]
            if len(file_h_m_s) == 1:
                file_h_m_s.insert(0, 0)
            if len(file_h_m_s) == 2:
                file_h_m_s.insert(0, 0)

            file_length_s = file_h_m_s[0] * 3600 + file_h_m_s[1] * 60 + file_h_m_s[2]
            if file_length_s < 60:
                file_length_min = 1
            else:
                # Convert seconds to minutes and round down
                file_length_min = int(round(file_length_s / 60))

        context.user_data["video_duration"] = file_length_min

        for f in info_dict["formats"]:
            height = f.get("height")
            width = f.get("width")
            ext = f.get("ext")
            filesize = f.get("filesize")
            if filesize is not None:
                filesize = filesize / 1024 / 1024
            if height is not None and width is not None and height >= 144:
                if isYoutube:
                    resolution_value = f"{height}p"
                    resolutions_and_sizes[resolution_value] = filesize
                else:
                    resolution_value = f"{width}x{height}"
                    resolutions_and_sizes[resolution_value] = filesize

        resolutions = [
            InlineKeyboardButton(
                f"{resolution}, (~{round(size, 2)} MB)" if size is not None else f"{resolution}",
                callback_data=resolution,
            )
            for resolution, size in resolutions_and_sizes.items()
        ]

        resolution_rows = [resolutions[i : i + 2] for i in range(0, len(resolutions), 2)]

        text = persistent.get_translation(context, "prompt_resolution_choice_text")

        if len(info_dict["formats"]) >= 1 and len(resolutions) == 0:
            persistent.logger.info("No resolution were found. Using the default resolution.")
            text = persistent.get_translation(context, "no_resolution_found_text")
            resolution_rows = [
                [
                    InlineKeyboardButton(
                        persistent.get_translation(context, "download_button_text"), callback_data="unknown"
                    )
                ]
            ]

        if len(resolution_rows) != 0:
            reply_markup = InlineKeyboardMarkup(resolution_rows)

            if height is not None and width is not None and context.user_data["user_font_size"] == "default":
                context.user_data["font_size"] = 14 if height > width else 22

            context.user_data["message"] = await update.message.reply_text(text, reply_markup=reply_markup)
        else:
            raise Exception("No resolutions were found")


async def handle_resolution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query

    selected_resolution = query.data

    context.user_data["selected_resolution"] = selected_resolution

    await query.answer()

    persistent.logger.info(f"{context.user_data['name']} selected resolution: {selected_resolution}")

    await select_language(update, context, original_language=True)
    return ORIGINAL_LANGUAGE


async def handle_video_or_document(update: Update, context: CallbackContext) -> int:
    try:

        if context.user_data.get("running_task"):
            return ConversationHandler.END

        persistent.check_settings(update, context)

        context.user_data["link"] = None
        user_id = context.user_data["user_id"]

        persistent.logger.info(
            f"{context.user_data['name']} (id: {user_id}; username: {context.user_data['username']}) has initalized a conversation."
        )
        persistent.logger.info("Downloading a file...")
        context.user_data["message"] = await update.message.reply_text(
            persistent.get_translation(context, "downloading_video_text")
        )
        context.user_data["video_path"] = video_path = f"{user_id}/video.mp4"
        if not os.path.exists(user_id):
            os.makedirs(user_id)

        # if update.message.video:
        file_id = update.message.video.file_id
        try:
            file = await context.bot.get_file(file_id, read_timeout=300)
            await file.download_to_drive(video_path)
            del file

        except Exception as e:
            traceback.print_exc()
            persistent.logger.info(f"Exception while trying to download a file.")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=persistent.get_translation(context, "file_downloading_error"),
            )
            return ConversationHandler.END
        video_path = file.file_path
        persistent.logger.info("Downloaded succesfully...")
        context.user_data["video_path"] = video_path
        context.user_data["document"] = True
        context.user_data["video_duration"] = (
            1 if update.message.video.duration < 60 else int(update.message.video.duration / 60)
        )  # seconds
        if context.user_data["user_font_size"] == "default":
            context.user_data["font_size"] = get_font_size(video_path)
        await select_language(update, context, original_language=True)
        return ORIGINAL_LANGUAGE

    except Exception as e:
        traceback.print_exc()
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=persistent.get_translation(context, "general_error")
        )


def upload_to_aws(local_file, bucket, s3_file, session):
    s3 = session.client("s3")

    try:
        s3.upload_file(local_file, bucket, s3_file)
        persistent.logger.info("Uploaded on S3 succesfully.")
        return True
    except FileNotFoundError:
        persistent.logger.info("The file was not found!")
        return False
    except NoCredentialsError:
        persistent.logger.info("Credentials not available!")
        return False


async def select_language(update: Update, context: ContextTypes.DEFAULT_TYPE, original_language: bool = False):
    other_languages = [
        (lang, LANGUAGE_CODES[lang], FLAG_CODES[lang])
        for lang in LANGUAGE_CODES.keys()
        if lang != "Detect" and lang != "Original"
    ]

    language_rows = [other_languages[i : i + 3] for i in range(0, len(other_languages), 3)]

    languages = (
        [[("Detect", "Detect", "")]] if original_language else [[("Original", "Original", "")]]
    ) + language_rows

    inline_keyboard = [
        [
            InlineKeyboardButton(f"{language_to_flag(flag_code)} {lang}", callback_data=lang_code)
            for lang, lang_code, flag_code in row
        ]
        for row in languages
    ]
    markup = InlineKeyboardMarkup(inline_keyboard)

    text = (
        persistent.get_translation(context, "prompt_original_language_selection_text")
        if original_language
        else persistent.get_translation(context, "prompt_language_selection_text")
    )

    if (
        original_language
        and (context.user_data.get("user_resolution") == "highest" or context.user_data.get("transcribe") == "yes")
        and not context.user_data.get("document")
    ):
        context.user_data["message"] = await context.bot.send_message(
            chat_id=context.user_data["chat_id"], text=text, reply_markup=markup
        )
    else:
        await context.user_data["message"].edit_text(text, reply_markup=markup)


async def close_bot(bot):
    y = await bot.log_out()
    x = await bot.close()
    print(f"Succesfull = {x}; y = {y}")


async def send_initial_message(self, bot):
    user_ids = persistent.get_user_ids()
    message = ""

    for user_id in user_ids:
        try:
            await bot.send_message(user_id, message, parse_mode="Markdown")
            self.logger.info("Message sent succesfully")
        except Exception as e:  # It's good to catch specific exceptions or log the general exception
            self.logger.info(f"An error occurred while sending a message to user {user_id}: {e}")


if __name__ == "__main__":
    application = (
        Application.builder()
        .token(TOKEN)
        .base_url("http://localhost:8081/bot")
        .base_file_url("http://localhost:8081/file/bot")
        .local_mode(True)
        .build()
    )
    job_queue = application.job_queue
    # job_queue.run_repeating(keep_warm, interval=550, first=10)

    # asyncio.get_event_loop().run_until_complete(close_bot(application.bot))
    # asyncio.get_event_loop().run_until_complete(send_initial_message(application.bot))

    language_pattern = re.compile("|".join(list(LANGUAGE_CODES.values())))

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(
                filters.TEXT & (filters.Entity(MessageEntity.URL) | filters.Entity(MessageEntity.TEXT_LINK)),
                handle_link,
            ),
            # MessageHandler(filters.VIDEO, handle_video_or_document),
        ],
        states={
            LINK: [
                MessageHandler(
                    filters.TEXT & (filters.Entity(MessageEntity.URL) | filters.Entity(MessageEntity.TEXT_LINK)),
                    handle_link,
                ),
                MessageHandler(filters.Document.MP4 | filters.VIDEO, handle_video_or_document),
            ],
            RESOLUTION: [CallbackQueryHandler(handle_resolution, pattern=r"^\d+p$|^\d+x\d+$|^unknown$")],
            ORIGINAL_LANGUAGE: [CallbackQueryHandler(handle_original_language, pattern=language_pattern)],
            TRANSLATION_LANGUAGE: [CallbackQueryHandler(handle_language, pattern=language_pattern)],
            BURN_OR_DISPLAY: [CallbackQueryHandler(handle_burn_or_display, pattern="^burn$|^display$")],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    style_handler = ConversationHandler(
        entry_points=[
            CommandHandler("style", style),
            MessageHandler(filters.Regex("Subtitles Style 🎨"), style),
        ],
        states={
            FONT: [CallbackQueryHandler(style_font_choice, pattern="^font_")],
            FONTSIZE: [CallbackQueryHandler(style_fontsize_choice, pattern="^fontsize_")],
            BORDERSTYLE: [CallbackQueryHandler(style_border_style_choice, pattern="^border_")],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)

    application.add_handler(style_handler)

    application.add_handler(CommandHandler("list", list_websites))

    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(CommandHandler("language", bot_language))

    application.add_handler(CommandHandler("resolution", resolution))

    application.add_handler(CommandHandler("transcribe", transcribe_command))

    application.add_handler(CommandHandler("translate_to", translateto))

    application.add_handler(CommandHandler("subtitle_choice", subtitle))

    application.add_handler(CommandHandler("minutes", show_available_minutes))

    application.add_handler(CommandHandler("reset", reset_settings))

    application.add_handler(CommandHandler("buy_minutes", select_minutes_command))

    application.add_handler(MessageHandler(filters.Regex("List Websites 📝"), list_websites))

    application.add_handler(MessageHandler(filters.Regex("Start 🔥"), start))

    application.add_handler(MessageHandler(filters.Regex("Help 🆘"), help_command))

    application.add_handler(MessageHandler(filters.Regex("Bot's Language 🌐"), bot_language))

    application.add_handler(MessageHandler(filters.Regex("Video Resolution 📺"), resolution))

    application.add_handler(MessageHandler(filters.Regex("Transcription 🗒"), transcribe_command))

    application.add_handler(MessageHandler(filters.Regex("Translation Language"), translateto))

    application.add_handler(MessageHandler(filters.Regex("Display Choice 🎬"), subtitle))

    application.add_handler(MessageHandler(filters.Regex("Balance ⏰"), show_available_minutes))

    application.add_handler(MessageHandler(filters.Regex("Reset ⚙"), reset_settings))

    application.add_handler(MessageHandler(filters.Regex("Buy Minutes 💵"), select_minutes_command))

    application.add_handler(MessageHandler(filters.Regex("Contact Support 🤝"), support_command))

    application.add_handler(CallbackQueryHandler(pattern="^subtitle_(.*)$", callback=subtitle_choice_handler))

    application.add_handler(CallbackQueryHandler(pattern="^minutes(.*)$", callback=handle_minutes_selection))

    application.add_handler(CallbackQueryHandler(pattern="^resolution(.*)$", callback=resolution_choice))

    application.add_handler(CallbackQueryHandler(pattern="^transcribe_(.*)$", callback=handle_transcribe_command))

    application.add_handler(CallbackQueryHandler(pattern="^translateto_(.*)$", callback=language_command_choice))

    application.add_handler(CallbackQueryHandler(pattern="^language_(.*)$", callback=bot_language_choice))

    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))

    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    try:
        application.run_polling(drop_pending_updates=True)

    except Exception as e:
        traceback.print_exc()
    finally:
        persistent.close_connection()
