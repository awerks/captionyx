import re
import subprocess
import json
import os
from typing import Any, Callable, Iterator, List, Optional, Union


def to_ms(**kwargs: Union[float, int, str]) -> int:
    hour = int(kwargs.get("hour", 0))
    minute = int(kwargs.get("min", 0))
    sec = int(kwargs.get("sec", 0))
    ms = int(kwargs.get("ms", 0))

    return (hour * 60 * 60 * 1000) + (minute * 60 * 1000) + (sec * 1000) + ms


def get_font_size(path):
    (width, height) = get_video_resolution(path)

    return 14 if height > width else 22


def get_audio(input_path, message, context):
    output_path = os.path.splitext(input_path)[0] + ".mp3"
    audio_extraction_process = subprocess.run(
        [
            "ffmpeg",
            "-i",
            input_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "320k",
            output_path,
            "-y",
            "-loglevel",
            "error",
        ]
    )

    return output_path, audio_extraction_process.returncode


def get_video_duration(video_path):
    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {video_path}"
    output = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=True)
    try:
        duration_in_seconds = float(output.stdout.decode("utf-8").strip())
    except ValueError as e:
        raise ValueError(f"Could not convert output to float: {output.stdout.decode('utf-8').strip()}") from e

    if duration_in_seconds < 60:
        return 1
    else:
        duration_in_minutes = round(duration_in_seconds / 60)
        return int(duration_in_minutes)


def get_video_resolution(video_path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        video_path,
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        output = json.loads(result.stdout)

        width = output["streams"][0]["width"]
        height = output["streams"][0]["height"]
        # duration = int(float(output["streams"][0]["duration"]))

        return (width, height)

    except subprocess.CalledProcessError as e:
        print(f"An error occurred: {e}")
        return None


class FfmpegProgress:
    DUR_REGEX = re.compile(r"Duration: (?P<hour>\d{2}):(?P<min>\d{2}):(?P<sec>\d{2})\.(?P<ms>\d{2})")
    TIME_REGEX = re.compile(r"out_time=(?P<hour>\d{2}):(?P<min>\d{2}):(?P<sec>\d{2})\.(?P<ms>\d{2})")

    def __init__(self, cmd: List[str], dry_run: bool = False) -> None:
        self.cmd = cmd
        self.dry_run = dry_run
        self.process: Any = None
        self.base_popen_kwargs = {
            "stdin": subprocess.PIPE,  # Apply stdin isolation by creating separate pipe.
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "universal_newlines": False,
        }

    def run_command_with_progress(self, duration_override: Optional[int] = None) -> Iterator[int]:
        if self.dry_run:
            return self.cmd

        cmd_with_progress = [self.cmd[0]] + ["-progress", "-", "-nostats"] + self.cmd[1:]

        total_dur: Optional[int] = None

        self.process = subprocess.Popen(cmd_with_progress, **self.base_popen_kwargs)

        yield 0

        while True:
            if self.process.stdout is None:
                continue

            stderr_line = self.process.stdout.readline().decode("utf-8", errors="replace").strip()
            # print(stderr_line)  # Print the output from ffmpeg
            if stderr_line == "" and self.process.poll() is not None:
                break

            if total_dur is None:
                total_dur_match = self.DUR_REGEX.search(stderr_line)
                if total_dur_match:
                    total_dur = to_ms(**total_dur_match.groupdict())
                    continue
                elif duration_override is not None:
                    total_dur = int(duration_override * 1000)
                    continue

            if total_dur:
                progress_time = FfmpegProgress.TIME_REGEX.search(stderr_line)
                if progress_time:
                    elapsed_time = to_ms(**progress_time.groupdict())
                    yield int((elapsed_time / total_dur) * 100)

        if self.process.returncode != 0:
            raise RuntimeError("Error running command")

        yield 100
        self.process = None
