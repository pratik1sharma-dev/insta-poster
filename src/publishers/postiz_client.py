"""
Postiz API Client - Handles Instagram posting via Postiz.
"""
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
import os
from dotenv import load_dotenv
import requests
import json
from src.models import GeneratedContent, ContentStrategy, PostResult
from src.config import settings


class PostizClient:
    """Client for Postiz API to publish Instagram posts."""

    def __init__(self):
        """Initialize Postiz client."""
        load_dotenv() # Load environment variables from .env file

        self.api_url = os.getenv("POSTIZ_API_URL")
        self.api_key = os.getenv("POSTIZ_API_KEY")
        self.r2_base_url = os.getenv("R2_BASE_URL")
        self.headers = {
            "Authorization": f"{self.api_key}",
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
            # Upload images first - now returns a list of dictionaries with image metadata
            uploaded_image_objects = self._upload_images(images)

            # Get Instagram integration ID for this logical channel
            integration_id = self._get_instagram_integration_id(channel)
            if not integration_id:
                return PostResult(
                    post_id=None,
                    timestamp=datetime.now(),
                    channel=channel,
                    content=content,
                    strategy=strategy,
                    status="failed",
                    error_message="No Instagram integration ID found.",
                    image_paths=[str(img) for img in images],
                )

            # Prepare post data
            post_data = self._prepare_post_data(content, strategy, uploaded_image_objects, channel, integration_id)

            # Create post
            print(f"DEBUG: Scheduling post to {self.api_url}/public/v1/posts")
            print(f"DEBUG: Request headers for post scheduling: {{'Authorization': '**********', 'Content-Type': 'application/json'}}")
            print(f"DEBUG: Request body for post scheduling: {json.dumps(post_data, indent=2)}")

            response = requests.post(
                f"{self.api_url}/public/v1/posts",
                headers=self.headers,
                json=post_data,
                timeout=30,
            )

            if response.status_code in [200, 201]:
                result_data = response.json()
                # Assuming result_data is a list with one dictionary as confirmed by debug output
                post_info = result_data[0] # Get the first (and only) dictionary
                return PostResult(
                    post_id=post_info.get("postId"), # Correctly extract postId
                    timestamp=datetime.now(),
                    channel=channel,
                    content=content,
                    strategy=strategy,
                    performance_tracking_url=None, # Not returned in this response, set to None
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

    def publish_reel(
        self,
        video_path: Path,
        content: GeneratedContent,
        strategy: ContentStrategy,
        channel: str,
        dry_run: bool = False,
    ) -> PostResult:
        """
        Publish a Reel to Instagram via Postiz.
        """
        if dry_run:
            return PostResult(
                post_id=None,
                timestamp=datetime.now(),
                channel=channel,
                content=content,
                strategy=strategy,
                status="dry_run",
                image_paths=[str(video_path)],
            )

        try:
            # 1. Upload Video
            uploaded_video_object = self._upload_video(video_path)

            # 2. Get Integration
            integration_id = self._get_instagram_integration_id(channel)
            if not integration_id:
                raise Exception("No Instagram integration ID found for Reel posting.")

            # 3. Prepare Reel Data
            full_caption = f"{content.caption}\n\n{' '.join(content.hashtags)}"
            schedule_date = datetime.now() + timedelta(minutes=10) # Reels might take longer to process
            SCHEDULE_DATE = schedule_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            reel_data = {
                "type": "schedule",
                "date": SCHEDULE_DATE,
                "shortLink": False,
                "tags": [],
                "posts": [
                    {
                        "integration": { "id": integration_id },
                        "value": [
                            {
                                "content": full_caption,
                                "image": [uploaded_video_object],
                            }
                        ],
                        "settings": {
                            "__type": "instagram",
                            "post_type": "post",
                        },
                        "channel": channel,
                    }
                ]
            }

            # DEBUG LOGGING
            print(f"DEBUG: Scheduling Reel to {self.api_url}/public/v1/posts")
            print(f"DEBUG: Request body for Reel: {json.dumps(reel_data, indent=2)}")

            response = requests.post(
                f"{self.api_url}/public/v1/posts",
                headers=self.headers,
                json=reel_data,
                timeout=30,
            )

            print(f"DEBUG: Reel response status: {response.status_code}")
            print(f"DEBUG: Reel response body: {response.text}")

            if response.status_code in [200, 201]:
                return PostResult(
                    post_id=response.json()[0].get("postId"),
                    timestamp=datetime.now(),
                    channel=channel,
                    content=content,
                    strategy=strategy,
                    status="success",
                    image_paths=[str(video_path)],
                )
            else:
                raise Exception(f"Postiz Reel API Error: {response.text}")

        except Exception as e:
            return PostResult(
                post_id=None,
                timestamp=datetime.now(),
                channel=channel,
                content=content,
                strategy=strategy,
                status="failed",
                error_message=str(e),
                image_paths=[str(video_path)],
            )

    def get_post_analytics(self, post_id: str) -> Optional[dict]:
        """
        Fetch performance metrics for a post via Postiz API.

        Returns dict with like_count, comments_count, saved, reach — or None on failure.
        All values may be 0 for new channels with no followers.
        """
        try:
            response = requests.get(
                f"{self.api_url}/public/v1/posts/{post_id}/analytics",
                headers=self.headers,
                timeout=15,
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "like_count": data.get("like_count") or data.get("likes") or 0,
                    "comments_count": data.get("comments_count") or data.get("comments") or 0,
                    "saved": data.get("saved") or data.get("saves") or 0,
                    "reach": data.get("reach") or data.get("impressions") or 0,
                }
            else:
                return None
        except Exception:
            return None

    def _upload_video(self, video_path: Path) -> dict:
        """Upload video file to Postiz."""
        with open(video_path, "rb") as f:
            files = {"file": (video_path.name, f, "video/mp4")}
            print(f"DEBUG: Uploading video '{video_path.name}' to {self.api_url}/public/v1/upload")
            
            response = requests.post(
                f"{self.api_url}/public/v1/upload",
                headers={"Authorization": self.api_key},
                files=files,
                timeout=120, # Increased timeout for video uploads
            )
            
            print(f"DEBUG: Video upload status: {response.status_code}")
            print(f"DEBUG: Video upload body: {response.text}")

            if response.status_code in [200, 201]:
                res = response.json()
                return {
                    "id": res.get("id"),
                    "name": res.get("name"),
                    "path": res.get("path"),
                    "thumbnail": None,
                }
            else:
                raise Exception(f"Failed to upload video: {response.text}")

    def _upload_images(self, images: List[Path]) -> List[dict]: # Changed return type
        """
        Upload images to Postiz and get media IDs and metadata.

        Args:
            images: List of image paths

        Returns:
            List of dictionaries with image metadata (id, name, path, etc.)
        """
        uploaded_image_objects = [] # Changed variable name

        for image_path in images:
            with open(image_path, "rb") as f:
                files = {"file": (image_path.name, f, "image/png")}
                print(f"DEBUG: Uploading image '{image_path.name}' to {self.api_url}/public/v1/upload")
                print(f"DEBUG: Request headers for upload: {{'Authorization': '**********'}}")
                # print(f"DEBUG: Request files for upload: {files}") # This can be very verbose, only enable if needed

                response = requests.post(
                    f"{self.api_url}/public/v1/upload",
                    headers={"Authorization": self.api_key},
                    files=files,
                    timeout=30,
                )
                print(f"DEBUG: Upload response status: {response.status_code}")
                print(f"DEBUG: Upload response body: {response.text}")

                if response.status_code in [200, 201]:
                    result = response.json()
                    media_id = result.get("id")
                    media_name = result.get("name")
                    media_path_from_response = result.get("path") # Get path directly from response

                    image_object = {
                        "id": media_id,
                        "name": media_name,
                        "path": media_path_from_response, # Use path from response
                        "thumbnail": None,
                        "alt": None,
                    }
                    uploaded_image_objects.append(image_object)
                else:
                    raise Exception(
                        f"Failed to upload {image_path.name}: {response.text}"
                    )

        return uploaded_image_objects

    def _get_instagram_integration_id(self, channel: str) -> Optional[str]:
        """
        Retrieves the Instagram integration ID from Postiz.

        Preference:
        - Match integration where identifier == "instagram" AND profile matches channel (case-insensitive).
        - If no such integration exists, return None and skip posting.
        """
        try:
            print(f"DEBUG: Retrieving Instagram integrations from {self.api_url}/public/v1/integrations")
            print(f"DEBUG: Request headers for integrations: {{'Authorization': '**********'}}")
            response = requests.get(
                f"{self.api_url}/public/v1/integrations",
                headers=self.headers,
                timeout=10,
            )
            print(f"DEBUG: Integrations response status: {response.status_code}")
            print(f"DEBUG: Integrations response body: {response.text}")

            if response.status_code == 200:
                integrations = response.json()

                # Try profile match (case-insensitive) for this channel
                channel_lc = (channel or "").lower()
                for integration in integrations:
                    if integration.get("identifier") != "instagram":
                        continue
                    profile = (integration.get("profile") or "").lower()
                    if profile == channel_lc:
                        print(
                            f"DEBUG: Found Instagram integration for channel '{channel}' "
                            f"with profile '{integration.get('profile')}' and ID: {integration.get('id')}"
                        )
                        return integration.get("id")

                print(
                    f"DEBUG: No Instagram integration found matching profile '{channel}' "
                    "(case-insensitive). No post will be created."
                )
                return None
            else:
                print(f"ERROR: Failed to get integrations: HTTP {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"ERROR: Error getting integrations: {e}")
            return None

    def _prepare_post_data(
        self,
        content: GeneratedContent,
        strategy: ContentStrategy,
        uploaded_image_objects: List[dict], # Changed to this
        channel: str,
        integration_id: str,
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
        full_caption = f"{content.caption}\n\n{' '.join(content.hashtags)}"
        
        # Temporarily generate schedule_date here for testing the structure
        schedule_date = datetime.now() + timedelta(minutes=5)
        SCHEDULE_DATE = schedule_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        return {
            "type": "schedule", # As per shell script
            "date": SCHEDULE_DATE, # As per shell script
            "shortLink": False, # As per shell script
            "tags": [], # As per shell script
            "posts": [
                {
                    "integration": { "id": integration_id }, # As per shell script
                    "value": [
                        {
                            "content": full_caption, # Using 'content' as per shell script
                            "image": uploaded_image_objects, # Using the rich image objects directly
                        }
                    ],
                    "settings": {
                        "__type": "instagram",
                        "post_type": "post",
                    },
                    "channel": channel, # Keeping channel here for now, might move to integration in future
                }
            ]
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
