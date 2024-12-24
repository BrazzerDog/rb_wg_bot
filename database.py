import sqlite3
from datetime import datetime

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('users.db', check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            birth_date TEXT,
            first_name TEXT,
            last_name TEXT,
            patronymic TEXT,
            phone_number TEXT,
            military_spec TEXT,
            dental_sanation BOOLEAN,
            medical_certificates BOOLEAN,
            foreign_passport BOOLEAN,
            active_contracts BOOLEAN,
            registration_date TIMESTAMP,
            is_banned BOOLEAN DEFAULT FALSE
        )
        ''')
        self.conn.commit()

    def add_user(self, user_id, data):
        try:
            # Валидация данных перед вставкой
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValueError("Invalid user_id")
            
            required_fields = ['birth_date', 'first_name', 'last_name', 'patronymic', 
                              'phone_number', 'military_spec']
            for field in required_fields:
                if not isinstance(data.get(field), str):
                    raise ValueError(f"Invalid {field}")
                
            boolean_fields = ['dental_sanation', 'medical_certificates', 
                             'foreign_passport', 'active_contracts']
            for field in boolean_fields:
                if not isinstance(data.get(field), bool):
                    raise ValueError(f"Invalid {field}")
            
            cursor = self.conn.cursor()
            # Используем параметризованный запрос для защиты от SQL-инъекций
            cursor.execute('''
            INSERT INTO users (
                user_id, birth_date, first_name, last_name, patronymic,
                phone_number, military_spec, dental_sanation, medical_certificates,
                foreign_passport, active_contracts, registration_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, data['birth_date'], data['first_name'], data['last_name'],
                data['patronymic'], data['phone_number'], data['military_spec'],
                data['dental_sanation'], data['medical_certificates'],
                data['foreign_passport'], data['active_contracts'], datetime.now()
            ))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise e

    def ban_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET is_banned = TRUE WHERE user_id = ?', (user_id,))
        self.conn.commit()

    def is_user_banned(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else False 

    def get_user_attempts(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE user_id = ?', (user_id,))
        return cursor.fetchone()[0] 