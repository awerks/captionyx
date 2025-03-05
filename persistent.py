import os
import psycopg2
import logging
import json
from datetime import datetime, timezone


class Persistent:
    """
    A singleton class that provides persistent storage and database operations.

    Attributes:
                    _instance (Persistent): The singleton instance of the class.
                    logger (Logger): The logger object for logging messages.
                    default_setting (str): The default setting value.
                    default_available_minutes (int): The default available minutes value.
                    data (dict): The loaded translations data.
                    list_of_supported_languages (list): The list of supported languages.
                    conn (psycopg2.extensions.connection): The database connection object.
                    cur (psycopg2.extensions.cursor): The database cursor object.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)

            # move the initializion logic from __init__ to __new__
            logging.basicConfig(
                format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%d-%b-%y %H:%M:%S", level=logging.INFO
            )
            cls._instance.logger = logging.getLogger(__name__)
            cls._instance.default_setting = "default"
            cls._instance.default_available_minutes = 60
            cls._instance.load_translations("translations/translations.json")
            cls._instance.connect_to_database()
            cls._instance.create_tables_if_not_exist()

            print("Creating a new class.")
        else:
            print("Returning the existing class.")
        return cls._instance

    def __init__(self):
        pass

    def load_translations(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        self.list_of_supported_languages = list(self.data.keys())

    def get_translation(self, context, text_key):
        return self.data[context.user_data["bot_language"]][text_key]

    def connect_to_database(self):

        if os.environ.get("production") == "True":
            self.conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        else:
            self.conn = psycopg2.connect(os.getenv("DATABASE_PUBLIC_URL"))

        self.cur = self.conn.cursor()

    def create_tables_if_not_exist(self):
        self.cur.execute(
            """
			CREATE TABLE IF NOT EXISTS users (
				user_id TEXT PRIMARY KEY,
				username TEXT,
				name TEXT,
				start_time_utc TIMESTAMP,
				bot_language TEXT,
				user_font_size TEXT,
				user_font TEXT,
				user_border_style TEXT,
				default_language TEXT,
				default_resolution TEXT,
				transcribe TEXT,
				subtitle_choice TEXT,
				available_minutes INTEGER
			)
		"""
        )

        self.conn.commit()

        self.cur.execute(
            """
			CREATE TABLE IF NOT EXISTS videos (
				id SERIAL PRIMARY KEY,
				user_id TEXT NOT NULL,
				username TEXT,
				name TEXT,
				link TEXT NOT NULL,
				sent_time_utc TIMESTAMP NOT NULL,
				duration_min INTEGER,
				resolution TEXT,
				selected_language TEXT,
				is_transcription BOOLEAN,
				FOREIGN KEY (user_id) REFERENCES users (user_id)
			)
		"""
        )
        self.conn.commit()

    def get_user_data(self, user_id):
        try:
            self.cur.execute(
                f"""
				SELECT user_id, username, name, start_time_utc, bot_language, user_font, user_font_size, user_border_style, default_language, default_resolution, transcribe, subtitle_choice, available_minutes
				FROM users
				WHERE user_id = '{user_id}'
			"""
            )
            return self.cur.fetchone()
        except Exception as e:
            self.logger.info(f"Error: {e}")
            return None

    def check_settings(
        self,
        update,
        context,
    ) -> None:
        if "bot_language" in context.user_data:
            return

        user_id = str(update.message.from_user.id)
        db_data = self.get_user_data(user_id)
        context.user_data["chat_id"] = update.effective_chat.id
        if db_data is None:
            name = (
                f"{update.message.from_user.first_name} {update.message.from_user.last_name}"
                if update.message.from_user.last_name
                else update.message.from_user.first_name
            )
            # If the user data is not found in the database, determine the bot_language setting and save it to the database.
            bot_language = (
                update.message.from_user.language_code
                if update.message.from_user.language_code in self.list_of_supported_languages
                else "en"
            )

            if bot_language == "ru":
                bot_language = "uk"

            self.save_user_settings(context, user_id, update.message.from_user.username, name, bot_language)
        else:
            context.user_data.update(
                dict(
                    zip(
                        [
                            "user_id",
                            "username",
                            "name",
                            "start_time_utc",
                            "bot_language",
                            "user_font",
                            "user_font_size",
                            "user_border_style",
                            "default_language",
                            "default_resolution",
                            "transcribe",
                            "subtitle_choice",
                            "available_minutes",
                        ],
                        db_data,
                    )
                )
            )

    def save_user_settings(self, context, user_id, username, name, bot_language):
        try:
            start_time_utc = datetime.now(timezone.utc)  # get the current date and time
            self.cur.execute(
                f"""
				INSERT INTO users (user_id, username, name, start_time_utc, bot_language, user_font_size, user_font, user_border_style, default_language, default_resolution, transcribe, subtitle_choice, available_minutes)
				VALUES ('{user_id}', '{username}', '{name}', '{start_time_utc}', '{bot_language}', '{self.default_setting}', '{self.default_setting}', '{self.default_setting}', '{self.default_setting}', '{self.default_setting}', '{self.default_setting}', '{self.default_setting}', '{self.default_available_minutes}')
			"""
            )
            self.conn.commit()

            context.user_data.update(
                {
                    "user_id": user_id,
                    "username": username,
                    "name": name,
                    "bot_language": bot_language,
                    "start_time_utc": start_time_utc,
                    "user_font": self.default_setting,
                    "user_font_size": self.default_setting,
                    "user_border_style": self.default_setting,
                    "default_language": self.default_setting,
                    "default_resolution": self.default_setting,
                    "transcribe": self.default_setting,
                    "subtitle_choice": self.default_setting,
                    "available_minutes": self.default_available_minutes,
                }
            )

        except Exception as e:
            self.logger.info(f"Error: {e}")
            self.conn.rollback()

    def save_video(
        self,
        user_id,
        username,
        name,
        link,
        duration_min,
        resolution,
        selected_language,
        is_transcription,
    ):
        try:
            sent_time_utc = datetime.utcnow()
            self.cur.execute(
                f"""
				INSERT INTO videos (user_id, username, name, link, sent_time_utc, duration_min, resolution, selected_language, is_transcription)
				VALUES ('{user_id}', '{username}', '{name}', '{link}', '{sent_time_utc}', '{duration_min}', '{resolution}', '{selected_language}', '{is_transcription}')
			"""
            )
            self.conn.commit()
        except Exception as e:
            self.logger.info(f"Error saving the video:\n{e}")
            self.conn.rollback()

    def update_field(self, user_id, field_name, field_value):
        try:
            self.cur.execute(
                f"""
				UPDATE users 
				SET {field_name} = '{field_value}'
				WHERE user_id = '{user_id}' AND {field_name} IS DISTINCT FROM '{field_value}'
			"""
            )
            self.conn.commit()
        except Exception as e:
            self.logger.info(f"Error: {e}")
            self.conn.rollback()

    def reset_settings(self, user_id, context):
        try:
            self.cur.execute(
                f"""
				UPDATE users 
				SET user_font = '{self.default_setting}',
					user_font_size = '{self.default_setting}',
					user_border_style = '{self.default_setting}',
					default_language = '{self.default_setting}',
					default_resolution = '{self.default_setting}',
					transcribe = '{self.default_setting}',
					subtitle_choice = '{self.default_setting}'
				WHERE user_id = '{user_id}'
			"""
            )
            self.conn.commit()

            context.user_data.update(
                {
                    "user_font": self.default_setting,
                    "user_font_size": self.default_setting,
                    "user_border_style": self.default_setting,
                    "default_language": self.default_setting,
                    "default_resolution": self.default_setting,
                    "transcribe": self.default_setting,
                    "subtitle_choice": self.default_setting,
                }
            )

        except Exception as e:
            self.logger.info(f"Error: {e}")
            self.conn.rollback()

    def get_user_ids(self):
        # Retrieve user IDs from the database

        self.cur.execute("SELECT user_id FROM users")

        return [int(row[0]) for row in self.cur.fetchall()]

    def close_connection(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()
