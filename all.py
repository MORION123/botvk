import os
import vk_api
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('VK_TOKEN')
GROUP_ID = 237271112

if not TOKEN:
    logger.error("Нет токена!")
    exit(1)

try:
    vk_session = vk_api.VkApi(token=TOKEN)
    vk = vk_session.get_api()
    
    # Просто получаем информацию о группе
    group = vk.groups.getById(group_id=GROUP_ID)
    logger.info(f"✅ Подключение успешно! Группа: {group[0]['name']}")
    
    # Пытаемся получить последние сообщения (просто тест)
    logger.info("Проверка доступа к сообщениям...")
    # Этот вызов проверит, есть ли права на сообщения
    vk.messages.getConversations(count=1)
    logger.info("✅ Доступ к сообщениям есть")
    
except Exception as e:
    logger.error(f"❌ Ошибка: {e}")
