import sqlite3
import os
import time
from datetime import datetime

class Database:
    def __init__(self, db_file='bot.db'):
        # Автоматически выбираем правильный путь для базы данных
        self.db_path = self.get_database_path(db_file)
        
        # Создаём папку для БД, если её нет
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        # Подключаемся к БД
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        print(f"✅ База данных: {self.db_path}")
    
    def get_database_path(self, db_file):
        """Определяет правильный путь для БД в зависимости от окружения"""
        
        # Список возможных путей в порядке приоритета
        possible_paths = [
            '/data/bot.db',                    # Bothost (рекомендуется)
            '/tmp/bot.db',                     # Временная папка
            os.path.join(os.getcwd(), 'data', 'bot.db'),  # Папка data в проекте
            os.path.join(os.getcwd(), db_file),          # Папка с проектом
        ]
        
        # Проверяем, какой путь доступен для записи
        for path in possible_paths:
            try:
                # Проверяем папку
                dir_path = os.path.dirname(path)
                if dir_path:
                    if not os.path.exists(dir_path):
                        os.makedirs(dir_path, exist_ok=True)
                # Пробуем создать тестовый файл
                test_file = os.path.join(dir_path, '.write_test')
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                print(f"📁 Выбран путь для БД: {path}")
                return path
            except:
                continue
        
        # Если ничего не подошло, используем временную папку
        print(f"⚠️ Используем временную папку /tmp/ для БД")
        return '/tmp/bot.db'
    
    def create_tables(self):
        """Создание всех таблиц"""
        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                vip_expires INTEGER DEFAULT 0,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица заданий
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_type TEXT,
                link TEXT,
                limit_count INTEGER,
                completed INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица выполненных действий
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                executor_id INTEGER,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        ''')
        
        # Таблица для заявок на вывод баллов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        self.conn.commit()
        print("✅ Таблицы созданы/проверены")
    
    def register_user(self, user_id):
        """Регистрация нового пользователя"""
        try:
            self.cursor.execute(
                "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
                (user_id,)
            )
            self.conn.commit()
        except Exception as e:
            print(f"Ошибка регистрации пользователя {user_id}: {e}")
    
    def get_user_balance(self, user_id):
        """Получение баланса пользователя"""
        self.cursor.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else 0
    
    def add_balance(self, user_id, amount):
        """Добавление баллов пользователю"""
        try:
            self.cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Ошибка добавления баланса: {e}")
            return False
    
    def remove_balance(self, user_id, amount):
        """Списание баллов"""
        current = self.get_user_balance(user_id)
        if current >= amount:
            self.cursor.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                (amount, user_id)
            )
            self.conn.commit()
            return True
        return False
    
    def create_task(self, user_id, task_type, link, limit_count):
        """Создание нового задания"""
        try:
            self.cursor.execute('''
                INSERT INTO tasks (user_id, task_type, link, limit_count)
                VALUES (?, ?, ?, ?)
            ''', (user_id, task_type, link, limit_count))
            self.conn.commit()
            return self.cursor.lastrowid
        except Exception as e:
            print(f"Ошибка создания задания: {e}")
            return None
    
    def get_user_tasks(self, user_id, active_only=True):
        """Получение заданий пользователя"""
        query = "SELECT * FROM tasks WHERE user_id = ?"
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY created_at DESC"
        
        self.cursor.execute(query, (user_id,))
        return self.cursor.fetchall()
    
    def get_task_by_id(self, task_id):
        """Получение задания по ID"""
        self.cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return self.cursor.fetchone()
    
    def delete_task(self, task_id, user_id):
        """Удаление задания (мягкое)"""
        try:
            self.cursor.execute(
                "UPDATE tasks SET active = 0 WHERE id = ? AND user_id = ?",
                (task_id, user_id)
            )
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            print(f"Ошибка удаления задания: {e}")
            return False
    
    def increment_task_completed(self, task_id):
        """Увеличение счётчика выполненных заданий"""
        try:
            self.cursor.execute('''
                UPDATE tasks 
                SET completed = completed + 1 
                WHERE id = ? AND completed < limit_count
            ''', (task_id,))
            self.conn.commit()
            
            # Проверяем, выполнено ли задание полностью
            self.cursor.execute(
                "SELECT completed, limit_count FROM tasks WHERE id = ?",
                (task_id,)
            )
            completed, limit_count = self.cursor.fetchone()
            
            if completed >= limit_count:
                self.cursor.execute(
                    "UPDATE tasks SET active = 0 WHERE id = ?",
                    (task_id,)
                )
                self.conn.commit()
                return True  # Задание выполнено полностью
            return False
        except Exception as e:
            print(f"Ошибка обновления задания: {e}")
            return False
    
    def get_all_active_tasks(self, exclude_user_id=None):
        """Получение всех активных заданий для выполнения"""
        query = "SELECT * FROM tasks WHERE active = 1 AND completed < limit_count"
        if exclude_user_id:
            query += f" AND user_id != {exclude_user_id}"
        query += " ORDER BY created_at ASC"
        
        self.cursor.execute(query)
        return self.cursor.fetchall()
    
    def has_completed_task(self, task_id, executor_id):
        """Проверка, выполнял ли пользователь уже это задание"""
        self.cursor.execute(
            "SELECT id FROM completions WHERE task_id = ? AND executor_id = ?",
            (task_id, executor_id)
        )
        return self.cursor.fetchone() is not None
    
    def add_completion(self, task_id, executor_id):
        """Запись о выполнении задания"""
        try:
            self.cursor.execute(
                "INSERT INTO completions (task_id, executor_id) VALUES (?, ?)",
                (task_id, executor_id)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Ошибка записи выполнения: {e}")
            return False
    
    def get_task_stats(self, user_id):
        """Статистика по заданиям пользователя"""
        self.cursor.execute(
            "SELECT COUNT(*), SUM(completed) FROM tasks WHERE user_id = ? AND active = 0",
            (user_id,)
        )
        completed_tasks, total_completions = self.cursor.fetchone()
        
        self.cursor.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND active = 1",
            (user_id,)
        )
        active_tasks = self.cursor.fetchone()[0]
        
        return {
            'active_tasks': active_tasks or 0,
            'completed_tasks': completed_tasks or 0,
            'total_completions': total_completions or 0
        }
    
    def add_vip(self, user_id, days):
        """Добавление VIP статуса"""
        expires = int(time.time()) + (days * 86400)
        self.cursor.execute(
            "UPDATE users SET vip_expires = ? WHERE user_id = ?",
            (expires, user_id)
        )
        self.conn.commit()
    
    def check_vip(self, user_id):
        """Проверка VIP статуса"""
        self.cursor.execute(
            "SELECT vip_expires FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()
        if result and result[0] > int(time.time()):
            return True
        return False
    
    def create_withdrawal_request(self, user_id, amount):
        """Создание заявки на вывод"""
        try:
            self.cursor.execute(
                "INSERT INTO withdrawal_requests (user_id, amount) VALUES (?, ?)",
                (user_id, amount)
            )
            self.conn.commit()
            return self.cursor.lastrowid
        except Exception as e:
            print(f"Ошибка создания заявки: {e}")
            return None
    
    def get_withdrawal_requests(self, status='pending'):
        """Получение заявок на вывод"""
        self.cursor.execute(
            "SELECT * FROM withdrawal_requests WHERE status = ? ORDER BY created_at ASC",
            (status,)
        )
        return self.cursor.fetchall()
    
    def update_withdrawal_status(self, request_id, status):
        """Обновление статуса заявки"""
        self.cursor.execute(
            "UPDATE withdrawal_requests SET status = ? WHERE id = ?",
            (status, request_id)
        )
        self.conn.commit()
    
    def get_top_users(self, limit=10):
        """Топ пользователей по баллам"""
        self.cursor.execute(
            "SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT ?",
            (limit,)
        )
        return self.cursor.fetchall()
    
    def get_total_users_count(self):
        """Общее количество пользователей"""
        self.cursor.execute("SELECT COUNT(*) FROM users")
        return self.cursor.fetchone()[0]
    
    def get_total_completions_count(self):
        """Общее количество выполненных заданий"""
        self.cursor.execute("SELECT COUNT(*) FROM completions")
        return self.cursor.fetchone()[0]
    
    def get_active_tasks_count(self):
        """Количество активных заданий"""
        self.cursor.execute("SELECT COUNT(*) FROM tasks WHERE active = 1")
        return self.cursor.fetchone()[0]
    
    def close(self):
        """Закрытие соединения с БД"""
        self.conn.close()
