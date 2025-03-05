from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, LabeledPrice, ReplyKeyboardMarkup
from telegram.ext import CallbackContext
from os import getenv
from utils import send_email_async, language_to_flag
from persistent import Persistent
from constants import LANGUAGE_CODES, FLAG_CODES, FONTS
import logging

persistent = Persistent()

PAYMENT_PROVIDER_TOKEN = getenv("PAYMENT_PROVIDER_TOKEN")
FONT, FONTSIZE, BORDERSTYLE = range(5, 8)
TO_KEEP_WARM = True
END = -1


async def start(update: Update, context: CallbackContext):
    persistent.check_settings(update, context)
    keyboard = [
        ["Start 🔥"],
        ["List Websites 📝", "Help 🆘"],
        ["Bot's Language 🌐", "Video Resolution 📺"],
        ["Transcription 🗒", "Translation Language"],
        ["Display Choice 🎬", "Subtitles Style 🎨"],
        ["Balance ⏰", "Reset ⚙"],
        ["Buy Minutes 💵", "Contact Support 🤝"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=False, resize_keyboard=True)

    if TO_KEEP_WARM:
        text = persistent.get_translation(context, "start_text")
    else:
        text = persistent.get_translation(context, "start_text_not_warm")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )
    persistent.logger.info(
        f"{context.user_data['name']} (id: {context.user_data['user_id']}; username: {context.user_data['username']}) has started a bot!"
    )


async def reset_settings(update: Update, context: CallbackContext) -> None:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} is resetting the settings.")
    persistent.reset_settings(context.user_data.get("user_id"), context)

    await update.message.reply_text(f"{persistent.get_translation(context, 'reset_setting_prompt')}")


async def translateto(update: Update, context: CallbackContext) -> int:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} is selecting a default language.")
    other_languages = [
        (lang, LANGUAGE_CODES[lang], FLAG_CODES[lang])
        for lang in LANGUAGE_CODES.keys()
        if lang != "Original" and lang != "Detect"
    ]

    # Arrange the languages in rows of four
    language_rows = [other_languages[i : i + 3] for i in range(0, len(other_languages), 3)]

    # Convert to InlineKeyboardMarkup
    inline_keyboard = []

    # Add 'Ask each time' and 'Original' as the first row
    inline_keyboard.append(
        [
            InlineKeyboardButton(persistent.get_translation(context, "ask"), callback_data="translateto_default"),
            InlineKeyboardButton(persistent.get_translation(context, "original"), callback_data="translateto_Original"),
        ]
    )

    for row in language_rows:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    f"{language_to_flag(flag_code)} {lang}",
                    callback_data=f"translateto_{lang_code}",
                )
                for lang, lang_code, flag_code in row
            ]
        )

    inline_keyboard.append(
        [InlineKeyboardButton(persistent.get_translation(context, "cancel"), callback_data="translateto_cancel")]
    )

    markup = InlineKeyboardMarkup(inline_keyboard)

    await update.message.reply_text(persistent.get_translation(context, "default_language_text"), reply_markup=markup)


async def language_command_choice(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    language = query.data.replace("translateto_", "")

    if language == "cancel":
        await query.edit_message_text(persistent.get_translation(context, "language_selection_cancelled_text"))
        return END

    if language == "default":
        await query.edit_message_text(persistent.get_translation(context, "prompt_each_time_text"))
    else:
        await query.edit_message_text(persistent.get_translation(context, "use_default_text"))

    persistent.logger.info(f"{context.user_data['name']} chose {language} as their default language.")
    context.user_data["default_language"] = language
    persistent.update_field(context.user_data.get("user_id"), "default_language", language)

    return END


async def transcribe_command(update: Update, context: CallbackContext) -> None:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} is selecting a transcribe option")
    # Define the keyboard
    keyboard = [
        [
            InlineKeyboardButton(persistent.get_translation(context, "transcription"), callback_data="transcribe_yes"),
            InlineKeyboardButton(persistent.get_translation(context, "subtitles"), callback_data="transcribe_default"),
        ],
        [InlineKeyboardButton(persistent.get_translation(context, "cancel"), callback_data="transcribe_cancel")],
    ]
    # Send the message with the keyboard
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        persistent.get_translation(context, "prompt_transcription_choice_text"), reply_markup=reply_markup
    )


async def handle_transcribe_command(update: Update, context: CallbackContext) -> None:
    # Handle the user's decision
    query = update.callback_query
    await query.answer()
    decision = query.data.replace("transcribe_", "")
    if decision == "cancel":
        await query.edit_message_text(text=persistent.get_translation(context, "transcription_cancelled_text"))
        return
    elif decision == "yes":
        await query.edit_message_text(text=persistent.get_translation(context, "plain_transcription_choice_text"))

    elif decision == "default":
        await query.edit_message_text(text=persistent.get_translation(context, "video_with_subtitles_choice_text"))

    persistent.logger.info(f"{context.user_data['name']} chose {decision} as a transcription option.")
    context.user_data["transcribe"] = decision
    persistent.update_field(context.user_data["user_id"], "transcribe", decision)


async def resolution(update: Update, context: CallbackContext) -> None:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} is selecting a resolution option")
    keyboard = [
        [
            InlineKeyboardButton(
                persistent.get_translation(context, "always_highest"), callback_data="resolution_highest"
            ),
            InlineKeyboardButton(persistent.get_translation(context, "ask"), callback_data="resolution_default"),
        ],
        [
            InlineKeyboardButton(persistent.get_translation(context, "cancel"), callback_data="resolution_cancel"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=persistent.get_translation(context, "prompt_resolution_choice_text"),
        reply_markup=reply_markup,
    )


async def resolution_choice(update: Update, context: CallbackContext) -> None:
    query = update.callback_query

    await query.answer()
    decision = query.data.replace("resolution_", "")
    if decision == "cancel":
        await query.edit_message_text(persistent.get_translation(context, "resolution_selection_cancelled_text"))
        return
    elif decision == "highest":
        await query.edit_message_text(text=persistent.get_translation(context, "resolution_update_confirmation_text"))
    else:
        await query.edit_message_text(text=persistent.get_translation(context, "prompt_each_time_text"))

    persistent.logger.info(f"{context.user_data['name']} selected {decision} resolution.")
    context.user_data["user_resolution"] = decision
    persistent.update_field(context.user_data["user_id"], "default_resolution", decision)


async def subtitle(update: Update, context: CallbackContext) -> None:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} is selecting a subtitle choice")
    keyboard = [
        [
            InlineKeyboardButton(
                persistent.get_translation(context, "burn_into_video_prompt"), callback_data="subtitle_burn"
            ),
            InlineKeyboardButton(
                persistent.get_translation(context, "display_website_prompt"), callback_data="subtitle_display"
            ),
        ],
        [
            InlineKeyboardButton(persistent.get_translation(context, "ask"), callback_data="subtitle_default"),
            InlineKeyboardButton(persistent.get_translation(context, "cancel"), callback_data="subtitle_cancel"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=persistent.get_translation(context, "prompt_subtitle_choice_text"),
        reply_markup=reply_markup,
    )


async def subtitle_choice_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    decision = query.data.replace("subtitle_", "")
    if decision == "cancel":
        await query.edit_message_text(persistent.get_translation(context, "subtitle_selection_cancelled_text"))
        return
    elif decision == "burn":
        await query.edit_message_text(text=persistent.get_translation(context, "subtitle_burn_confirmation_text"))
    elif decision == "display":
        await query.edit_message_text(text=persistent.get_translation(context, "subtitle_display_confirmation_text"))
    else:
        await query.edit_message_text(text=persistent.get_translation(context, "prompt_each_time_text"))

    persistent.logger.info(f"User selected {decision} for subtitles.")
    context.user_data["subtitle_choice"] = decision
    persistent.update_field(context.user_data["user_id"], "subtitle_choice", decision)


async def list_websites(update: Update, context: CallbackContext) -> None:
    persistent.check_settings(update, context)
    supported_websites = [
        "Pinterest",
        "Instagram",
        "LinkedIn",
        "Reddit",
        "TikTok",
        "Imgur",
        "YouTube",
        "Twitter",
        "Facebook",
    ]

    keyboard = [supported_websites[i : i + 3] for i in range(0, len(supported_websites), 3)]
    keyboard = [[InlineKeyboardButton(site, url=f"https://{site.lower()}.com") for site in row] for row in keyboard]

    keyboard.append(
        [
            InlineKeyboardButton(
                persistent.get_translation(context, "full_supported_websites_text"),
                url="https://teletype.in/@subtitlesgeneratorbot/uOhKZMs3-36",
            )
        ]
    )

    reply_markup = InlineKeyboardMarkup(keyboard)

    persistent.logger.info(f"{context.user_data['name']} requested a list of websites!")
    # Sending the message with the keyboard
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=persistent.get_translation(context, "supported_websites_text"),
        reply_markup=reply_markup,
    )


async def help_command(update: Update, context: CallbackContext) -> None:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} activated !help command.")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=persistent.get_translation(context, "bot_help_text"),
        parse_mode="Markdown",
    )


async def bot_language(update: Update, context: CallbackContext) -> None:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} is selecting a bot language.")
    keyboard = [
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="language_en"),
            InlineKeyboardButton("🇪🇸 Español", callback_data="language_es"),
            InlineKeyboardButton("🇵🇹 Português", callback_data="language_pt"),
        ],
        [
            InlineKeyboardButton("🇩🇪 Deutsche", callback_data="language_de"),
            InlineKeyboardButton("🇫🇷 Français", callback_data="language_fr"),
            InlineKeyboardButton("🇹🇷 Türkçe", callback_data="language_tr"),
        ],
        [
            InlineKeyboardButton("🇨🇳 中文", callback_data="language_zh"),
            InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="language_hi"),
            InlineKeyboardButton("🇰🇷 한국어", callback_data="language_ko"),
        ],
        [
            InlineKeyboardButton("🇳🇱 Nederlands", callback_data="language_nl"),
            InlineKeyboardButton("🇵🇱 Polskie", callback_data="language_pl"),
            InlineKeyboardButton("🇺🇦 Українська", callback_data="language_uk"),
        ],
        [
            InlineKeyboardButton("🇸🇦 العربية", callback_data="language_ar"),
            InlineKeyboardButton("Cancel", callback_data="language_cancel"),
            InlineKeyboardButton("🇮🇹 Italiano", callback_data="language_it"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        persistent.get_translation(context, "prompt_bot_language_text"), reply_markup=reply_markup
    )


async def bot_language_choice(update: Update, context: CallbackContext) -> None:
    query = update.callback_query

    await query.answer()

    decision = query.data.replace("language_", "")

    if decision == "cancel":
        await query.edit_message_text(text=persistent.get_translation(context, "language_selection_cancelled_text"))
    else:
        context.user_data["bot_language"] = decision
        await query.edit_message_text(text=persistent.get_translation(context, "selected_language_text"))
        persistent.logger.info(f"{context.user_data['name']} chose {decision} language.")
        persistent.update_field(context.user_data.get("user_id"), "bot_language", decision)


async def style(update: Update, context: CallbackContext) -> int:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} is selecting subtitles style.")
    if context.user_data.get("state") in [FONT, FONTSIZE, BORDERSTYLE]:
        context.user_data["state"] = END
    keyboard = [
        [
            InlineKeyboardButton(
                font.replace("-Bold", "").replace("-Medium", ""),
                callback_data=f"font_{font}",
            )
            for font in FONTS[i : i + 2]
        ]
        for i in range(0, len(FONTS), 2)
    ]
    keyboard.insert(
        0, [InlineKeyboardButton(persistent.get_translation(context, "default"), callback_data="font_default")]
    )  # Add "Default" button as the first row
    keyboard.append(
        [InlineKeyboardButton(persistent.get_translation(context, "cancel"), callback_data="font_cancel")]
    )  # Add "Cancel" button

    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=persistent.get_translation(context, "default_font_text"),
        reply_markup=reply_markup,
    )

    return FONT


async def style_font_choice(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    decision = query.data.replace("font_", "")
    if decision == "cancel":
        await query.edit_message_text(persistent.get_translation(context, "font_selection_cancelled_text"))
        return END
    else:
        context.user_data["user_font"] = decision
        persistent.update_field(context.user_data.get("user_id"), "user_font", decision)
    persistent.logger.info(f"{context.user_data['name']} chose {decision} font.")

    # Generates a list of numbers from 10 to 32 in steps of 2
    font_sizes = list(range(10, 33, 2))

    keyboard = [
        [
            InlineKeyboardButton(f"{font_sizes[n]}px", callback_data=f"fontsize_{font_sizes[n]}px")
            for n in range(i, min(i + 4, len(font_sizes)))
        ]
        for i in range(0, len(font_sizes), 4)
    ]
    keyboard.append(
        [InlineKeyboardButton(persistent.get_translation(context, "cancel"), callback_data="fontsize_cancel")]
    )  # Add "Cancel" button
    keyboard.insert(
        0,
        [InlineKeyboardButton(persistent.get_translation(context, "default"), callback_data="fontsize_default")],
    )  # Add "Default" button as the first row
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=persistent.get_translation(context, "default_fontsize_text"), reply_markup=reply_markup
    )

    return FONTSIZE


async def style_fontsize_choice(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    decision = query.data.replace("fontsize_", "")
    if decision == "cancel":
        await query.edit_message_text(persistent.get_translation(context, "fontsize_selection_cancelled_text"))
        return END
    else:
        # Save the selected font size
        context.user_data["user_font_size"] = decision
        persistent.update_field(context.user_data["user_id"], "user_font_size", decision)
    persistent.logger.info(f"{context.user_data['name']} chose {decision} fontsize.")

    keyboard = [
        [
            InlineKeyboardButton(persistent.get_translation(context, "box"), callback_data="border_box"),
            InlineKeyboardButton(persistent.get_translation(context, "none"), callback_data="border_default"),
        ]
    ]
    keyboard.append(
        [InlineKeyboardButton(persistent.get_translation(context, "cancel"), callback_data="border_cancel")]
    )
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=persistent.get_translation(context, "default_border_text"), reply_markup=reply_markup
    )

    return BORDERSTYLE


async def style_border_style_choice(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    decision = query.data.replace("border_", "")
    if decision == "cancel":
        await query.edit_message_text(persistent.get_translation(context, "style_selection_cancelled_text"))
        return END
    else:
        context.user_data["user_border_style"] = decision
        await query.edit_message_text(text=persistent.get_translation(context, "font_update_confirmation_text"))
        persistent.update_field(context.user_data.get("user_id"), "user_border_style", decision)

    persistent.logger.info(f"{context.user_data['name']} chose {decision} borderstyle.")

    return END


async def show_available_minutes(update: Update, context: CallbackContext) -> None:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} has requested a balance of available minutes.")
    available_minutes = context.user_data["available_minutes"]
    await update.message.reply_text(
        f"{persistent.get_translation(context, 'current_available_minutes_text')} {available_minutes}\n\n{persistent.get_translation(context, 'current_available_minutes_text_extra')}",
        parse_mode="Markdown",
    )


async def select_minutes_command(update: Update, context: CallbackContext) -> None:
    persistent.check_settings(update, context)
    persistent.logger.info(f"{context.user_data['name']} wants to buy more minutes!")
    # Define the inline keyboard
    keyboard = [
        [
            InlineKeyboardButton("30 minutes", callback_data="minutes_30"),
            InlineKeyboardButton("60 minutes", callback_data="minutes_60"),
        ],
        [
            InlineKeyboardButton("120 minutes", callback_data="minutes_120"),
            InlineKeyboardButton("180 minutes", callback_data="minutes_180"),
        ],
        [
            InlineKeyboardButton("300 minutes", callback_data="minutes_300"),
            InlineKeyboardButton("450 minutes", callback_data="minutes_450"),
        ],
        [InlineKeyboardButton("Cancel", callback_data="minutes_cancel")],
    ]
    # Send the message with the inline keyboard
    reply_markup = InlineKeyboardMarkup(keyboard)
    # prompt_minutes_choice
    await update.message.reply_text(
        persistent.get_translation(context, "prompt_minutes_choice"), reply_markup=reply_markup
    )


async def handle_minutes_selection(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    decision = query.data.replace("minutes_", "")
    if decision == "cancel":
        await query.edit_message_text(persistent.get_translation(context, "minutes_selection_cancelled_text"))
        return

    minutes = int(decision)
    title = "Subtitles Generator"
    description = f"{decision} minutes of subtitles/transcription/translation"
    payload = "Subtitles-Generator-Bot"
    currency = "EUR"

    context.user_data["price"] = price = minutes // 30

    prices = [LabeledPrice(label=f"{minutes} minutes of subtitles", amount=price * 100)]
    context.user_data["minutes_choice"] = minutes

    await query.delete_message()

    # await query.edit_message_text(f"Great! Now, you may purchase it via the official Telegram payment provider.")

    context.user_data["invoice_message"] = await context.bot.send_invoice(
        context.user_data["chat_id"],
        title,
        description,
        payload,
        PAYMENT_PROVIDER_TOKEN,
        currency,
        prices,
        need_email=True,
        send_email_to_provider=True,
    )


async def precheckout_callback(update: Update, context: CallbackContext) -> None:
    """Answers the PreQecheckoutQuery"""
    query = update.pre_checkout_query
    # check the payload, is this from your bot?
    if query.invoice_payload != "Subtitles-Generator-Bot":
        # answer False pre_checkout_query
        await query.answer(ok=False, error_message=persistent.get_translation(context, "purchase_payload_error"))
    else:
        await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: CallbackContext) -> None:
    context.user_data["available_minutes"] += context.user_data["minutes_choice"]
    persistent.update_field(context.user_data["user_id"], "available_minutes", context.user_data["available_minutes"])

    await update.message.reply_text(
        f"Thank you for your payment!\n\nYour current balance is: {context.user_data['available_minutes']} minutes"
    )

    await context.user_data["invoice_message"].delete()

    persistent.logger.info(f"{context.user_data['name']} purchased {context.user_data['minutes_choice']} minutes :)")
    email = update.message.successful_payment.order_info.email
    persistent.logger.info(f"Email: {email}")

    await send_email_async(
        email,
        context.user_data["name"],
        context.user_data["minutes_choice"],
        context.user_data["price"],
    )


async def support_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(persistent.get_translation(context, "support_text"))


# async def cancel_handler(update: Update, context: CallbackContext) -> int:
#     """Cancels and ends the conversation."""
#     await update.message.reply_text(get(context, "goodbye_text"), reply_markup=ReplyKeyboardRemove())
#     if os.path.exists(context.user_data["user_id"]):
#         shutil.rmtree(context.user_data["user_id"])

#     prediction = context.user_data.get("prediction")
#     if prediction:
#         context.user_data["available_minutes"] -= context.user_data["video_duration"]
#         prediction.cancel()
#         del context.user_data["prediction"]

#     if "message" in context.user_data:
#         del context.user_data["message"]

#

#     return END
