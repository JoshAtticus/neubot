from flask_login import UserMixin
from backend.database import get_db_connection

class User(UserMixin):
    def __init__(self, id, name, email, provider, profile_pic=None):
        self.id = id
        self.name = name
        self.email = email
        self.provider = provider
        self.profile_pic = profile_pic
        
    @staticmethod
    def get(user_id):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
            user_data = cursor.fetchone()
            
            if user_data:
                return User(
                    id=user_data['id'],
                    name=user_data['name'],
                    email=user_data['email'],
                    provider=user_data['provider'],
                    profile_pic=user_data['profile_pic']
                )
            return None
