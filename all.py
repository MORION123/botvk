import os
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import logging
import time

# Настройка логов
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    # Читаем токен из переменной окружения
    TOKEN = os.environ.get('VK_TOKEN')
    if not TOKEN:
        logger.error("VK_TOKEN не найден!")
        exit(1)
    
    GROUP_ID = 237271112  # ID вашего сообщества
    
    logger.info(f"Запуск тестового бота. GROUP_ID: {GROUP_ID}")
    
    try:
        # Подключаемся
        vk_session = vk_api.VkApi(token=TOKEN)
        vk = vk_session.get_api()
        longpoll = VkBotLongPoll(vk_session, GROUP_ID)
        
        logger.info("✅ Бот подключен. Ожидание сообщений...")
        
        # Слушаем события
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                msg = event.obj.message
                peer_id = msg['peer_id']
                from_id = msg['from_id']
                text = msg.get('text', '')
                
                logger.info(f"📩 Новое сообщение!")
                logger.info(f"   Peer ID: {peer_id}")
                logger.info(f"   From ID: {from_id}")
                logger.info(f"   Текст: {text}")
                
                # Отвечаем только в беседу с peer_id = 2000000204
                if peer_id == 2000000204:
                    try:
                        vk.messages.send(
                            peer_id=peer_id,
                            message=f"✅ Бот работает! Получено сообщение: {text[:50]}",
                            random_id=0
                        )
                        logger.info("✅ Ответ отправлен в беседу")
                    except Exception as e:
                        logger.error(f"❌ Ошибка при отправке ответа: {e}")
                        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
