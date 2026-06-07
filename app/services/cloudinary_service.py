import cloudinary
import cloudinary.uploader

from app.config import settings

cloudinary.config(
    cloudinary_url=settings.CLOUDINARY_URL
)