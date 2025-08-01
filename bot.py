from flask import Flask, request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, ContextTypes
from telegram.ext.filters import Text, Command
import requests
import xml.etree.ElementTree as ET
import csv
import io
import logging
import json
import asyncio

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
OLD_FEED, NEW_FEED = range(2)

# Глобальная переменная для Application
application = None

# Эндпоинт для проверки активности сервера (для UptimeRobot)
@app.route('/health')
def health_check():
    logger.info("Health check endpoint called")
    return Response("OK", status=200)

# Эндпоинт для обработки вебхука Telegram
@app.route('/webhook', methods=['POST'])
async def webhook():
    logger.info("Webhook endpoint called")
    try:
        update = Update.de_json(json.loads(request.get_data().decode('utf-8')), application.bot)
        await application.process_update(update)
        logger.info("Webhook processed successfully")
        return Response("OK", status=200)
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return Response(f"Error: {str(e)}", status=500)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запускает процесс сравнения, запрашивая URL старого фида."""
    logger.info(f"User {update.effective_user.id} started comparison")
    await update.message.reply_text("Send the URL of the old feed.")
    return OLD_FEED

async def get_old_feed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняет URL старого фида и запрашивает URL нового."""
    context.user_data['old_feed'] = update.message.text
    logger.info(f"Old feed URL received: {context.user_data['old_feed']}")
    await update.message.reply_text("Now send the URL of the new feed.")
    return NEW_FEED

async def compare_feeds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сравнивает фиды и отправляет отчет в виде CSV."""
    new_feed_url = update.message.text
    logger.info(f"New feed URL received: {new_feed_url}")
    
    try:
        # Загружаем фиды с таймаутом
        old_feed = requests.get(context.user_data['old_feed'], timeout=10).content
        new_feed = requests.get(new_feed_url, timeout=10).content
        
        # Парсим XML
        old_ids = set(el.text.strip() for el in ET.fromstring(old_feed).findall(".//Object/ExternalId") if el.text)
        new_ids = set(el.text.strip() for el in ET.fromstring(new_feed).findall(".//Object/ExternalId") if el.text)

        # Сравниваем ExternalId
        result = []
        for ext_id in old_ids:
            status = "Preserved" if ext_id in new_ids else "Missing"
            result.append([ext_id, status, "Exists in both feeds" if status == "Preserved" else "Not found in new feed"])
        for ext_id in new_ids - old_ids:
            result.append([ext_id, "New", "Only in new feed"])

        # Проверяем, есть ли данные
        if not result:
            await update.message.reply_text("No ExternalIds found in feeds.")
            logger.info("No ExternalIds found")
            return ConversationHandler.END

        # Формируем CSV-отчет
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ExternalId", "Status", "Details"])
        writer.writerows(result)
        output.seek(0)
        
        # Отправляем CSV как файл
        await update.message.reply_document(
            document=io.BytesIO(output.getvalue().encode('utf-8')),
            filename="feed_comparison.csv",
            caption="Comparison results"
        )
        logger.info("Comparison results sent as CSV")
        
    except requests.RequestException as e:
        await update.message.reply_text(f"Error fetching feeds: {str(e)}")
        logger.error(f"Request error: {str(e)}")
    except ET.ParseError as e:
        await update.message.reply_text(f"Invalid XML format: {str(e)}")
        logger.error(f"XML parse error: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")
        logger.error(f"Unexpected error: {str(e)}")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет процесс сравнения."""
    logger.info("Comparison cancelled")
    await update.message.reply_text("Comparison cancelled.")
    return ConversationHandler.END

async def main():
    """Запускает бот с вебхуком."""
    global application
    logger.info("Starting bot...")
    try:
        # Инициализация Application
        application = Application.builder().token("8054808302:AAGWzAFYyVWWdCaIi5TzVN-s905cBNtrTms").build()

        # Настраиваем ConversationHandler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("compare", start)],
            states={
                OLD_FEED: [MessageHandler(Text() & ~Command(), get_old_feed)],
                NEW_FEED: [MessageHandler(Text() & ~Command(), compare_feeds)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        
        application.add_handler(conv_handler)
        
        # Инициализация приложения
        await application.initialize()
        logger.info("Application initialized")

        # Установка вебхука
        logger.info("Setting up webhook...")
        await application.bot.set_webhook(url="https://cian-feed-comparator.onrender.com/webhook")
        logger.info("Webhook setup complete")
        
    except Exception as e:
        logger.error(f"Failed to start bot: {str(e)}")
        raise

if __name__ == "__main__":
    # Запускаем main в асинхронном режиме
    asyncio.run(main())
    # Запускаем Flask-сервер
    app.run(host="0.0.0.0", port=8443)