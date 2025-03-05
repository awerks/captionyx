import re
from conjunctions import get_conjunctions, get_comma
from utils import format_timestamp


class SubtitlesProcessor:
    def __init__(self, segments, lang, max_line_length=45, min_char_length_splitter=30, is_vtt=False):
        self.comma = get_comma(lang)
        self.conjunctions = set(get_conjunctions(lang))
        self.segments = segments
        self.lang = lang
        self.max_line_length = max_line_length
        self.min_char_length_splitter = min_char_length_splitter
        self.is_vtt = is_vtt
        complex_script_languages = [
            "th",
            "lo",
            "my",
            "km",
            "am",
            "ko",
            "ja",
            "zh",
            "ti",
            "ta",
            "te",
            "kn",
            "ml",
            "hi",
            "ne",
            "mr",
            "ar",
            "fa",
            "ur",
            "ka",
        ]
        if self.lang in complex_script_languages:
            self.max_line_length = 30
            self.min_char_length_splitter = 20

    def estimate_timestamp_for_word(self, words, i, next_segment_start_time=None):
        k = 0.25
        has_prev_end = i > 0 and "end" in words[i - 1]
        has_next_start = i < len(words) - 1 and "start" in words[i + 1]

        if has_prev_end:
            words[i]["start"] = words[i - 1]["end"]
            if has_next_start:
                words[i]["end"] = words[i + 1]["start"]
            else:
                if next_segment_start_time:
                    words[i]["end"] = (
                        next_segment_start_time
                        if next_segment_start_time - words[i - 1]["end"] <= 1
                        else next_segment_start_time - 0.5
                    )
                else:
                    words[i]["end"] = words[i]["start"] + len(words[i]["word"]) * k

        elif has_next_start:
            words[i]["start"] = words[i + 1]["start"] - len(words[i]["word"]) * k
            words[i]["end"] = words[i + 1]["start"]

        else:
            if next_segment_start_time:
                words[i]["start"] = next_segment_start_time - 1
                words[i]["end"] = next_segment_start_time - 0.5
            else:
                words[i]["start"] = 0
                words[i]["end"] = 0

    def process_segments(self, advanced_splitting=True, normal_handling=True):
        subtitles = []

        if not normal_handling:
            min_length = 10  # Minimum length of sentence to split, adjust as needed.
            new_segments = []

            for segment in self.segments:
                # Split text into sentences
                sentences = re.split("(?<=[.!?]) +", segment["text"])

                total_length = sum(len(sentence) for sentence in sentences)
                elapsed_time = 0  # Keep track of the time elapsed for previous sentences

                for i, sentence in enumerate(sentences):
                    # If the sentence is too short and it's not the last sentence in the list,
                    # append it to the next sentence.
                    if len(sentence) < min_length and i < len(sentences) - 1:
                        sentences[i + 1] = sentence + " " + sentences[i + 1]
                        continue  # skip to the next iteration, as we have merged the current sentence with the next one

                    sentence_length = len(sentence)
                    sentence_time_ratio = sentence_length / total_length  # Weight for the current sentence

                    sentence_time_interval = (segment["end"] - segment["start"]) * sentence_time_ratio

                    new_segment = {
                        "start": segment["start"] + elapsed_time,
                        "end": segment["start"] + elapsed_time + sentence_time_interval,
                        "text": sentence.strip(),
                    }

                    elapsed_time += sentence_time_interval  # Update the elapsed time

                    new_segments.append(new_segment)

            self.segments = new_segments

        for i, segment in enumerate(self.segments):
            next_segment_start_time = self.segments[i + 1]["start"] if i + 1 < len(self.segments) else None

            if advanced_splitting:
                split_points = self.determine_advanced_split_points(segment, next_segment_start_time)
                subtitles.extend(
                    self.generate_subtitles_from_split_points(segment, split_points, next_segment_start_time)
                )
            else:
                if normal_handling:
                    words = segment["words"]
                    for i, word in enumerate(words):
                        if "start" not in word or "end" not in word:
                            self.estimate_timestamp_for_word(words, i, next_segment_start_time)

                subtitles.append({"start": segment["start"], "end": segment["end"], "text": segment["text"]})

        return subtitles

    def determine_advanced_split_points(self, segment, next_segment_start_time=None):
        split_points = []
        last_split_point = 0
        char_count = 0

        words = segment.get("words", segment["text"].split())
        add_space = 0 if self.lang in ["zh", "ja"] else 1

        total_char_count = sum(len(word["word"]) if isinstance(word, dict) else len(word) + add_space for word in words)
        char_count_after = total_char_count

        for i, word in enumerate(words):
            word_text = word["word"] if isinstance(word, dict) else word
            word_length = len(word_text) + add_space
            char_count += word_length
            char_count_after -= word_length

            char_count_before = char_count - word_length

            if isinstance(word, dict) and ("start" not in word or "end" not in word):
                self.estimate_timestamp_for_word(words, i, next_segment_start_time)

            if (
                word_text.endswith(self.comma)
                and char_count_before >= self.min_char_length_splitter
                and char_count_after >= self.min_char_length_splitter
            ):
                split_points.append(i)
                last_split_point = i + 1
                char_count = 0

            elif (
                word_text.lower() in self.conjunctions
                and char_count_before >= self.min_char_length_splitter
                and char_count_after >= self.min_char_length_splitter
            ):
                split_points.append(i - 1)
                last_split_point = i
                char_count = word_length

            elif char_count >= self.max_line_length:
                midpoint = int((last_split_point + i) / 2)
                if char_count_before >= self.min_char_length_splitter:
                    split_points.append(midpoint)
                    last_split_point = midpoint + 1
                    char_count = sum(
                        len(words[j]["word"]) if isinstance(words[j], dict) else len(words[j]) + add_space
                        for j in range(last_split_point, i + 1)
                    )

        return split_points

    def generate_subtitles_from_split_points(self, segment, split_points, next_start_time=None):
        subtitles = []

        words = segment.get("words", segment["text"].split())
        total_word_count = len(words)
        total_time = segment["end"] - segment["start"]
        elapsed_time = segment["start"]
        prefix = " " if self.lang not in ["zh", "ja"] else ""
        start_idx = 0
        for split_point in split_points:
            fragment_words = words[start_idx : split_point + 1]
            current_word_count = len(fragment_words)

            if isinstance(fragment_words[0], dict):
                start_time = fragment_words[0]["start"]
                end_time = fragment_words[-1]["end"]
                next_start_time_for_word = words[split_point + 1]["start"] if split_point + 1 < len(words) else None
                if next_start_time_for_word and (next_start_time_for_word - end_time) <= 0.8:
                    end_time = next_start_time_for_word
            else:
                fragment = prefix.join(fragment_words).strip()
                current_duration = (current_word_count / total_word_count) * total_time
                start_time = elapsed_time
                end_time = elapsed_time + current_duration
                elapsed_time += current_duration

            subtitles.append(
                {
                    "start": start_time,
                    "end": end_time,
                    "text": (
                        fragment
                        if not isinstance(fragment_words[0], dict)
                        else prefix.join(word["word"] for word in fragment_words)
                    ),
                }
            )

            start_idx = split_point + 1

        # Handle the last fragment
        if start_idx < len(words):
            fragment_words = words[start_idx:]
            current_word_count = len(fragment_words)

            if isinstance(fragment_words[0], dict):
                start_time = fragment_words[0]["start"]
                end_time = fragment_words[-1]["end"]
            else:
                fragment = prefix.join(fragment_words).strip()
                current_duration = (current_word_count / total_word_count) * total_time
                start_time = elapsed_time
                end_time = elapsed_time + current_duration

            if next_start_time and (next_start_time - end_time) <= 0.8:
                end_time = next_start_time

            subtitles.append(
                {
                    "start": start_time,
                    "end": end_time if end_time is not None else segment["end"],
                    "text": (
                        fragment
                        if not isinstance(fragment_words[0], dict)
                        else prefix.join(word["word"] for word in fragment_words)
                    ),
                }
            )

        return subtitles

    def save(self, filename="subtitles.srt", advanced_splitting=True):
        subtitles = self.process_segments(advanced_splitting)
        last_end_time = subtitles[-1]["end"] if subtitles else 0
        ending_start_time = last_end_time + 1
        ending_end_time = last_end_time + 4.5
        text = "Captioning by\n<i>t.me/SubtitlesGeneratorBot</i>"
        subtitles.append({"start": ending_start_time, "end": ending_end_time, "text": text})

        def write_subtitle(file, idx, start_time, end_time, text):
            if not text:
                return 0
            file.write(f"{idx}\n")
            file.write(f"{start_time} --> {end_time}\n")
            file.write(text + "\n\n")

        with open(filename, "w", encoding="utf-8") as file:
            if self.is_vtt:
                file.write("WEBVTT\n\n")

            if advanced_splitting:
                for idx, subtitle in enumerate(subtitles, 1):
                    start_time = format_timestamp(subtitle["start"], self.is_vtt)
                    end_time = format_timestamp(subtitle["end"], self.is_vtt)
                    text = subtitle["text"].strip()
                    write_subtitle(file, idx, start_time, end_time, text)

        return len(subtitles)
