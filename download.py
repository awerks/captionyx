import asyncio
import re
import yt_dlp
from utils import progress_function
from constants import PROGRESS_BAR_STYLE, BAR_WIDTH
from persistent import Persistent
from telegram.ext import CallbackContext

persistent = Persistent()


async def download_video(url: str, context: CallbackContext):
    message = context.user_data["message"]
    last_fragment = [-1]
    last_progress = [-1]
    total_frags_count = [0]
    ydl_opts = {}

    def progress_hook(data):
        if data.get("status") == "downloading":
            total_frags = data.get("fragment_count", 1)
            current_frag = data.get("fragment_index", 0)
            progress_string = data.get("_percent_str", "0%")

            progress_values = re.findall(
                r"\d+\.\d+", progress_string
            )  # Finds any sequence of digits followed by a dot and digits again
            # persistent.logger.info(progress_values)

            if progress_values:  # If the list is not empty
                current_progress = int(float(progress_values[0]))
                # persistent.logger.info(f"current_progress: {current_progress}")
                # persistent.logger.info(f"current_frag: {current_frag}")
                if current_progress > 100:  # In case if progress is reported incorrectly
                    current_progress = 100
                # if current_frag == 0:
                # return

                bar = progress_function(0, 100, current_progress, BAR_WIDTH, progress_style=PROGRESS_BAR_STYLE)

                text_to_send = f"{persistent.get_translation(context, 'downloading_video_text')}<code>{bar} {current_progress}%</code>"

                if current_frag >= last_fragment[0] and current_progress - last_progress[0] >= 12:
                    asyncio.run_coroutine_threadsafe(message.edit_text(text_to_send, parse_mode="HTML"), loop)
                    last_fragment[0] = current_frag
                    last_progress[0] = current_progress

    output_path = f"{context.user_data['user_id']}/video.mp4"

    format_str = get_yt_dlp_format_str(url, context)

    ydl_opts.update(
        {
            "outtmpl": output_path,
            "format": format_str,
            "merge_output_format": "mp4",
            "concurrent_fragment_downloads": 16,
            "extractor_args": {"youtube": {"formats": ["dashy"]}},
            "noplaylist": True,
            "nooverwrites": False,
            "progress_hooks": [progress_hook],
            "noprogress": True,
            "quiet": True,
        }
    )
    last_update = 0

    loop = asyncio.get_running_loop()

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        await loop.run_in_executor(None, lambda: ydl.download([url]))

    return output_path


def get_yt_dlp_format_str(url: str, context: CallbackContext):
    vcodec = "[vcodec~='^((he|a)vc|h26[45])']"

    best_video_mp4 = "bestvideo[ext=mp4]"

    best_audio_m4a = "bestaudio[ext=m4a]"

    best_video_webm = "bestvideo[ext=webm]"

    best_audio_webm = "bestaudio[ext=webm]"

    best_video_and_audio = f"bestvideo+bestaudio"

    worst_video_mp4 = "worstvideo[ext=mp4]"

    worst_video_webm = "worstvideo[ext=webm]"

    best = "best"

    selected_resolution = context.user_data.get("selected_resolution")

    if selected_resolution == "unknown":
        format_str = "best"

    elif context.user_data.get("user_resolution") == "highest":
        format_str = f"{best_video_mp4}{vcodec}+{best_audio_m4a}/{best_video_webm}+{best_audio_webm}/{best_video_mp4}+{best_audio_m4a}/{best_video_and_audio}"

    elif context.user_data.get("transcribe") == "yes":
        format_str = f"{worst_video_mp4}{vcodec}+{best_audio_m4a}/{worst_video_webm}+{best_audio_webm}/{worst_video_mp4}+{best_audio_m4a}/{worst_video_mp4}+{best_audio_m4a}/{best_video_and_audio}"

    elif "youtube" in url or "youtu.be" in url:
        height = selected_resolution[:-1]

        format_str = f"{best_video_mp4}[height={height}]{vcodec}+{best_audio_m4a}/{best_video_webm}[height={height}]+{best_audio_webm}/{best_video_mp4}[height={height}]+{best_audio_m4a}/{best}[height={height}]"

    else:
        height = selected_resolution.split("x")[1]

        format_str = f"{best_video_mp4}[height={height}]{vcodec}+{best_audio_m4a}/{best_video_webm}[height={height}]+{best_audio_webm}/{best_video_mp4}[height={height}]+{best_audio_m4a}/{best}[height={height}]"

    return format_str
