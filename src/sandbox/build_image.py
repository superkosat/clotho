#!/usr/bin/env python3
"""Build the Clotho sandbox Docker image."""

import docker
import sys
from pathlib import Path


def build_sandbox_image():
    """Build the sandbox image from Dockerfile."""
    try:
        client = docker.from_env()

        dockerfile_path = Path(__file__).parent / "Dockerfile"
        if not dockerfile_path.exists():
            print(f"Error: Dockerfile not found at {dockerfile_path}")
            return False

        print("Building clotho-sandbox image...")
        print("This may take a few minutes on first run...\n")

        image, build_logs = client.images.build(
            path=str(dockerfile_path.parent),
            tag="clotho-sandbox:latest",
            rm=True,  # Remove intermediate containers
            forcerm=True,
        )

        # Print build logs
        for log in build_logs:
            if "stream" in log:
                print(log["stream"], end="")

        print(f"\n✓ Image built successfully: {image.tags[0]}")
        print(f"  Image ID: {image.short_id}")
        print(f"  Size: {image.attrs['Size'] / 1024 / 1024:.1f} MB")

        return True

    except docker.errors.DockerException as e:
        print(f"Error: Docker daemon not available: {e}")
        print("\nMake sure Docker is installed and running:")
        print("  - Docker Desktop (Windows/Mac)")
        print("  - dockerd service (Linux)")
        return False

    except Exception as e:
        print(f"Error building image: {e}")
        return False


if __name__ == "__main__":
    success = build_sandbox_image()
    sys.exit(0 if success else 1)
