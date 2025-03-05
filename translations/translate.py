import json
import os
import re
from google.cloud import translate_v2 as translate
from googletrans import Translator


def extract_and_replace_bracketed(text_list):
    modified_texts = []
    all_placeholders = []
    for text in text_list:
        placeholders = []
        modified_text = text
        for match in re.findall(r"\[([^\]]+)\]", text):
            placeholder = f"PLACEHOLDER_{len(placeholders)}"
            modified_text = modified_text.replace(f"[{match}]", placeholder, 1)
            placeholders.append(match)
        modified_texts.append(modified_text)
        all_placeholders.append(placeholders)
    return modified_texts, all_placeholders


def translate_text(text_list, target_lang: str) -> list:
    modified_texts, all_placeholders = extract_and_replace_bracketed(text_list)

    translator = Translator()

    translated_texts = []
    for modified_text, placeholders in zip(modified_texts, all_placeholders):
        if isinstance(modified_text, bytes):
            modified_text = modified_text.decode("utf-8")

        result = translator.translate(modified_text, dest=target_lang)
        translated_text = result.text

        for i, placeholder in enumerate(placeholders):
            translated_text = translated_text.replace(f"PLACEHOLDER_{i}", f"[{placeholder}]")

        translated_texts.append({"translatedText": translated_text})

    return translated_texts


def load_prompts(prompts_file: str) -> dict:
    with open(prompts_file, "r", encoding="utf-8") as f:
        return {line.split(":", maxsplit=1)[0]: line.split(":", maxsplit=1)[1].strip() for line in f.readlines()}


def load_translations(translations_file: str) -> dict:
    with open(translations_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_translations(translations_file: str, data: dict):
    with open(translations_file, "w", encoding="utf-8") as f:
        formatted_json_string = json.dumps(data, indent=4, ensure_ascii=False).replace("\\\\n", "\\n")
        f.write(formatted_json_string)


def main():
    translations_file = "backup.json"
    prompts_file = "prompts.txt"
    # os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials.json"

    data = load_translations(translations_file)
    languages = [lang for lang in data.keys() if lang != "en"]  # Exclude English
    prompts = load_prompts(prompts_file)

    for language in languages:
        print(f"Translating to {language}")
        if language == "zh":
            # Google Translate doesn't support zh, so use zh-CN instead
            translations = translate_text(list(prompts.values()), target_lang="zh-CN")
        else:
            translations = translate_text(list(prompts.values()), target_lang=language)
        for i, key in enumerate(prompts.keys()):
            formatted_english_prompt = re.sub(r"\[|\]", "", prompts[key])
            data["en"][key] = formatted_english_prompt  # Add original english text
            data[language][key] = translations[i]["translatedText"]

    save_translations(translations_file, data)


if __name__ == "__main__":
    main()
