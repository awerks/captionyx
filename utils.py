import aiosmtplib
import os
import subprocess
import secrets
import string
import math
from jinja2 import Environment, FileSystemLoader
from email.message import EmailMessage
from constants import BAR_STYLES
from datetime import datetime


def make_url_friendly_datetime():
    # Format datetime to a URL-friendly string

    return datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")


def isNowInTimePeriod(startTime, endTime, nowTime):
    if startTime < endTime:
        return nowTime >= startTime and nowTime <= endTime

    else:  # Over midnight
        return nowTime >= startTime or nowTime <= endTime


def format_timestamp(seconds: float, is_vtt: bool = False):
    assert seconds >= 0, "non-negative timestamp expected"

    milliseconds = round(seconds * 1000.0)

    hours = milliseconds // 3_600_000

    milliseconds -= hours * 3_600_000

    minutes = milliseconds // 60_000

    milliseconds -= minutes * 60_000

    seconds = milliseconds // 1_000

    milliseconds -= seconds * 1_000

    separator = "." if is_vtt else ","

    hours_marker = f"{hours:02d}:"

    return f"{hours_marker}{minutes:02d}:{seconds:02d}{separator}{milliseconds:03d}"


def progress_function(min, max, current, width, progress_style=0):
    style = BAR_STYLES[progress_style]

    q_max = len(style) * width

    ratio = float(current - min) / (max - min)

    q_current = int(ratio * q_max)

    return "".join(
        [
            style[-1] if x <= q_current else style[q_current - x] if x - q_current < len(style) else style[0]
            for x in [y * len(style) for y in range(1, width + 1)]
        ]
    )


def normal_round(n):
    if n - math.floor(n) < 0.5:
        return math.floor(n)

    return math.ceil(n)


def language_to_flag(language_code):
    if language_code is None or len(language_code) != 2:
        return ""

    # Convert language code to corresponding Unicode flag

    OFFSET = 127397

    code_upper = language_code.upper()

    return chr(ord(code_upper[0]) + OFFSET) + chr(ord(code_upper[1]) + OFFSET)


def generate_random_string(length=10):
    alphabet = string.ascii_letters + string.digits

    return "".join(secrets.choice(alphabet) for _ in range(length))


async def send_email_async(email_address, name, minutes_choice, price):
    EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER")

    EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")

    EMAIL_PORT = int(os.getenv("EMAIL_PORT"))

    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

    env = Environment(loader=FileSystemLoader("email_template"))

    text_template = env.get_template("email_template.txt")

    html_template = env.get_template("email_template.html")

    purchase_date = datetime.now().strftime("%B %d, %Y")

    currency = "€"

    text_body = text_template.render(
        purchase_date=purchase_date,
        name=name,
        date=purchase_date,
        amount=minutes_choice,
        total=f"{price}{currency}",
    )

    html_body = html_template.render(
        purchase_date=purchase_date,
        name=name,
        date=purchase_date,
        amount=minutes_choice,
        total=f"{price}{currency}",
    )

    message = EmailMessage()

    message["Subject"] = "Congratulations on Your Recent Purchase from Subtitles Generator!"

    message["From"] = EMAIL_USERNAME

    message["To"] = email_address

    message.set_content(text_body)

    message.add_alternative(html_body, subtype="html")

    await aiosmtplib.send(
        message,
        hostname=EMAIL_PROVIDER,
        port=EMAIL_PORT,
        username=EMAIL_USERNAME,
        password=EMAIL_PASSWORD,
        use_tls=True,
    )


def get_thumbnails(file_path):
    size = "7x7"

    jpg_folder = "temp/thumbnails/images"

    output_path = "temp/thumbnails/thumbnails.vtt"

    if os.path.exists(file_path):
        if not os.path.exists(jpg_folder):
            os.makedirs(jpg_folder)

        # Get video information

        command = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration,width,height",
            "-of",
            "csv=p=0",
            file_path,
        ]

        info = subprocess.check_output(command).decode("utf-8").strip().split(",")

        if len(info) == 3:
            duration = int(float(info[2]))

            aspect = int(info[0]) / int(info[1])

            width = int(info[0])

            height = int(info[1])

            if duration < 60:  # Less than 1 minute
                interval = 2  # Every 1 second

            elif duration < 180:  # 1-3 minutes
                interval = 5  # Every 2 seconds

            elif duration < 300:  # 3-5 minutes
                interval = 10  # Every 3 seconds

            elif duration < 600:  # 5-10 minutes
                interval = 20  # Every 5 seconds

            elif duration < 1800:  # 10-30 minutes
                interval = 30  # Every 10 seconds

            elif duration < 3600:  # 30-60 minutes
                interval = 50  # Every 20 seconds

            else:  # More than 1 hour
                interval = 100  # Every 30 seconds

            # Generate thumbnails

            command = [
                "ffmpeg",
                "-i",
                file_path,
                "-vsync",
                "vfr",
                "-vf",
                f"select=isnan(prev_selected_t)+gte(t-prev_selected_t\\,{interval}),scale={width}:{height},tile={size}",
                "-qscale:v",
                "5",
                f"{jpg_folder}/img%d.jpg",
                "-y",
                "-loglevel",
                "error",
            ]

            subprocess.run(command)

            size_split = size.split("x")

            vtt = "WEBVTT\n"

            counter = 0

            num_images = normal_round((duration / interval) / (int(size_split[0]) * int(size_split[1])))

            for jpg in range(1, num_images + 1):
                for col in range(int(size_split[0])):
                    for row in range(int(size_split[1])):
                        start_time = format_timestamp(counter * interval)

                        end_time = format_timestamp((counter + 1) * interval)

                        vtt += f"\n{start_time} --> {end_time}\nimages/img{jpg}.jpg#xywh={row * width},{col * height},{width},{height}\n"

                        counter += 1

            with open(output_path, "w") as f:
                f.write(vtt)

        else:
            print("Video info not found")

    else:
        print(f"File {file_path} not found")


def install_yt_dlp():
    try:
        subprocess.run(["pip3", "install", "yt-dlp"], check=True)

    except subprocess.CalledProcessError as e:
        print(f"An error occurred while updating pip, setuptools, and wheel: {e}")


def install_master_yt_dlp():
    try:
        master_link = "https://github.com/yt-dlp/yt-dlp/archive/master.tar.gz"

        subprocess.run(
            [
                "python3",
                "-m",
                "pip",
                "install",
                master_link,
            ],
            check=True,
        )

    except subprocess.CalledProcessError as e:
        print(f"An error occurred while installing yt-dlp: {e}")
