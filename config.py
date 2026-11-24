import hashlib
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OWNER_FACES_DIR = os.path.join(BASE_DIR, "owner_faces")
PASSWORD_HASH_FILE = os.path.join(BASE_DIR, "password.hash")
FACE_LANDMARKER_MODEL_PATH = os.path.join(BASE_DIR, "face_landmarker.task")

CAMERA_INDEX = 0
CHECK_INTERVAL_SEC = 2.0      # فحص الكاميرا كل ثانيتين
ABSENCE_LOCK_SEC = 6.0        # القفل بعد 6 ثواني غياب متواصل
AUTO_UNLOCK_ON_RETURN = True  # الفتح التلقائي عند العودة


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def save_password(password: str) -> None:
    with open(PASSWORD_HASH_FILE, "w", encoding="utf-8") as f:
        f.write(hash_password(password))


def verify_password(password: str) -> bool:
    if not os.path.exists(PASSWORD_HASH_FILE):
        return False
    with open(PASSWORD_HASH_FILE, "r", encoding="utf-8") as f:
        saved_hash = f.read().strip()
    return hash_password(password) == saved_hash