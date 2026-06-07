import cloudinary
import cloudinary.uploader
from ..config import settings



cloudinary.config(
    cloudinary_url=settings.CLOUDINARY_URL
)

class CloudinaryService:

    @staticmethod
    def upload_file(file):
        result = cloudinary.uploader.upload(
            file,
            folder=settings.CLOUDINARY_FOLDER,
            resource_type="auto"
        )

        return {
            "url": result["secure_url"],
            "public_id": result["public_id"]
        }

    @staticmethod
    def delete_file(public_id: str):
        return cloudinary.uploader.destroy(public_id)