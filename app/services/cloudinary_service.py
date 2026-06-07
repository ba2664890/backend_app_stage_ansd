import cloudinary
import cloudinary.uploader

from config import settings

cloudinary.config(
    cloudinary_url=settings.CLOUDINARY_URL
)