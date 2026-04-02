import os
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import logging
import time

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ЧТЕНИЕ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ====================
TOKEN = os.environ.get('VK_TOKEN')
PEER_ID = int(os.environ.get('PEER_ID', 2000000204))  # ваша беседа
GROUP_ID = int(os.environ.get('GROUP_ID', 237271112))  # ваше сообщество

if __name__ == '__main__':
    # Проверка наличия токена
    if not TOKEN:
        logger.error("❌ VK_TOKEN не найден в переменных окружения!")
        exit(1)
    
    logger.info(f"🚀 Запуск тестового бота")
    logger.info(f"   GROUP_ID: {GROUP_ID}")
    logger.info(f"   PEER_ID (целевая беседа): {PEER_ID}")
    
    try:
        # Подключение к VK API
        vk_session = vk_api.VkApi(token=TOKEN)
        vk = vk_session.get_api()
        longpoll = VkBotLongPoll(vk_session, GROUP_ID)
        
        logger.info("✅ Бот успешно подключен к Long Poll API")
        logger.info("📡 Ожидание сообщений...")
        
        # Основной цикл обработки событий
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                msg = event.obj.message
                peer_id = msg['peer_id']
                from_id = msg['from_id']
                text = msg.get('text', '')
                
                logger.info(f"📩 Получено сообщение")
                logger.info(f"   Peer ID: {peer_id}")
                logger.info(f"   From ID: {from_id}")
                logger.info(f"   Текст: {text[:100]}")
                
                # Отвечаем ТОЛЬКО в целевую беседу
                if peer_id == PEER_ID:
                    try:
                        # Отправляем ответ
                        response_text = f"✅ Бот работает!\n\nПолучено сообщение:\n{text[:200]}"
                        vk.messages.send(
                            peer_id=peer_id,
                            message=response_text,
                            random_id=0
                        )
                        logger.info(f"✅ Ответ отправлен в беседу {PEER_ID}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка при отправке ответа: {e}")
                else:
                    logger.info(f"⏩ Игнорируем сообщение из беседы {peer_id} (ожидаем {PEER_ID})")
                    
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        logger.info("Перезапуск через 5 секунд...")
        time.sleep(5)
