"""
Postiz API Client - Handles Instagram posting via Postiz.
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import requests
from src.models import GeneratedContent, ContentStrategy, PostResult
from src.config import settings


class PostizClient:
    """Client for Postiz API to publish Instagram posts."""

    def __init__(self):
        """Initialize Postiz client."""
        self.api_url = settings.postiz_api_url
        self.api_key = settings.postiz_api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def health_check(self) -> bool:
        """
        Check if Postiz API is accessible.

        Returns:
            True if API is accessible, False otherwise
        """
        try:
            response = requests.get(
                f"{self.api_url}/health",
                headers=self.headers,
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Health check failed: {e}")
            return False

    def publish_post(
        self,
        images: List[Path],
        content: GeneratedContent,
        strategy: ContentStrategy,
        channel: str,
        dry_run: bool = False,
    ) -> PostResult:
        """
        Publish carousel post to Instagram via Postiz.

        Args:
            images: List of paths to carousel images
            content: Generated content
            strategy: Content strategy
            channel: Channel name
            dry_run: If True, don't actually post

        Returns:
            PostResult with publishing details
        """
        if dry_run:
            return PostResult(
                post_id=None,
                timestamp=datetime.now(),
                channel=channel,
                content=content,
                strategy=strategy,
                status="dry_run",
                image_paths=[str(img) for img in images],
            )

        try:
            # Upload images first
            media_ids = self._upload_images(images)

            # Prepare post data
            post_data = self._prepare_post_data(content, strategy, media_ids, channel)

            # Create post
            response = requests.post(
                f"{self.api_url}/public/v1/posts",
                headers=self.headers,
                json=post_data,
                timeout=30,
            )

            if response.status_code in [200, 201]:
                result_data = response.json()
                return PostResult(
                    post_id=result_data.get("id"),
                    timestamp=datetime.now(),
                    channel=channel,
                    content=content,
                    strategy=strategy,
                    performance_tracking_url=result_data.get("url"),
                    status="success",
                    image_paths=[str(img) for img in images],
                )
            else:
                return PostResult(
                    post_id=None,
                    timestamp=datetime.now(),
                    channel=channel,
                    content=content,
                    strategy=strategy,
                    status="failed",
                    error_message=f"HTTP {response.status_code}: {response.text}",
                    image_paths=[str(img) for img in images],
                )

        except Exception as e:
            return PostResult(
                post_id=None,
                timestamp=datetime.now(),
                channel=channel,
                content=content,
                strategy=strategy,
                status="failed",
                error_message=str(e),
                image_paths=[str(img) for img in images],
            )

    def _upload_images(self, images: List[Path]) -> List[str]:
        """
        Upload images to Postiz and get media IDs.

        Args:
            images: List of image paths

        Returns:
            List of media IDs from Postiz
        """
        media_ids = []

        for image_path in images:
            with open(image_path, "rb") as f:
                files = {"file": (image_path.name, f, "image/png")}

                response = requests.post(
                    f"{self.api_url}/public/v1/upload",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files=files,
                    timeout=30,
                )

                if response.status_code in [200, 201]:
                    result = response.json()
                    media_ids.append(result.get("id"))
                else:
                    raise Exception(
                        f"Failed to upload {image_path.name}: {response.text}"
                    )

        return media_ids

    def _prepare_post_data(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        media_ids: List[str],
        channel: str,
    ) -> dict:
        """
        Prepare post data for Postiz API.

        Args:
            content: Generated content
            strategy: Content strategy
            media_ids: List of uploaded media IDs
            channel: Channel name

        Returns:
            Post data dictionary
        """
        # Combine caption with hashtags
        full_caption = f"{content.caption}\n\n{' '.join(content.hashtags)}"

        return {
            "platform": "instagram",
            "channel": channel,
            "content": full_caption,
            "media": media_ids,
            "type": "carousel",
            "metadata": {
                "topic": strategy.topic,
                "hook_type": strategy.hook_type,
                "visual_style": strategy.visual_style,
            },
        }

    def get_post_analytics(self, post_id: str) -> Optional[dict]:
        """
        Get analytics for a published post.

        Args:
            post_id: Post ID from Postiz

        Returns:
            Analytics data or None if not available
        """
        try:
            response = requests.get(
                f"{self.api_url}/posts/{post_id}/analytics",
                headers=self.headers,
                timeout=10,
            )

            if response.status_code == 200:
                return response.json()
            return None

        except Exception as e:
            print(f"Failed to get analytics: {e}")
            return None
