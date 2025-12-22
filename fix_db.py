from app.database import engine
from sqlalchemy import text

def migrate():
    with engine.connect() as connection:
        # Add current_title to user_profiles
        try:
            connection.execute(text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS current_title VARCHAR(255);"))
            connection.execute(text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS experience_years INTEGER;"))
            connection.commit()
            print("Successfully added columns to user_profiles")
        except Exception as e:
            print(f"Error updating user_profiles: {e}")

        # Ensure role exists in users table (just in case)
        try:
            connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'candidate';"))
            connection.commit()
            print("Successfully checked role column in users")
        except Exception as e:
            print(f"Error updating users: {e}")

if __name__ == "__main__":
    migrate()
