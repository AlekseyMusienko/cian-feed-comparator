from flask import Flask, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
import requests
import xml.etree.ElementTree as ET
import csv
import io
import logging

app = Flask(__name__)

# Настройка логирования для отладки
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
OLD_FEED, NEW_FEED = range(2)

# Эндпоинт для проверки активности сервера (для UptimeRobot)
@app.route('/health')
def health_check():
    return Response("OK", status=200)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запускает процесс сравнения, запрашивая URL старого фида."""
    await update.message.reply_text("Send the URL of the old feed.")
    return OLD_FEED

async def get_old_feed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохраняет URL старого фида и запрашивает URL нового."""
    context.user_data['old_feed'] = update.message.text
    await update.message.reply_text("Now send the URL of the new feed.")
    return NEW_FEED

async def compare_feeds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сравнивает фиды и отправляет отчет в виде CSV."""
    new_feed_url = update.message.text
    old_feed_url = context.user_data['old_feed']
    
    try:
        # Загружаем фиды с таймаутом
        old_feed = requests.get(old_feed_url, timeout=10).content
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
        
    except requests.RequestException as e:
        await update.message.reply_text(f"Error fetching feeds: {str(e)}")
    except ET.ParseError as e:
        await update.message.reply_text(f"Invalid XML format: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет процесс сравнения."""
    await update.message.reply_text("Comparison cancelled.")
    return ConversationHandler.END

def main():
    """Запускает бот с вебхуком."""
    # Используем предоставленный токен
    application = Application.builder().token("8054808302:AAGWzAFYyVWWdCaIi5TzVN-s905cBNtrTms").build()

    # Настраиваем ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("compare", start)],
        states={
            OLD_FEED: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_old_feed)],
            NEW_FEED: [MessageHandler(filters.TEXT & ~filters.COMMAND, compare_feeds)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    application.add_handler(conv_handler)
    
    # Запускаем бот с вебхуком
    application.run_webhook(
        listen="0.0.0.0",
        port=8443,
        url_path="/webhook",
        webhook_url="https://cian-feed-comparator.onrender.com/webhook"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8443)