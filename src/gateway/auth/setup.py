import sys

from gateway.auth.token import generate_token, load_token, save_token


def run_setup() -> str:
    existing = load_token()
    if existing:
        print(f"Token already exists. To regenerate, run: clotho setup --force")
        return existing

    token = generate_token()
    save_token(token)
    print(f"Generated API token: {token}")
    print(f"Store this token securely. Clients use it to authenticate with the gateway.")
    return token


def main():
    force = "--force" in sys.argv
    if force:
        token = generate_token()
        save_token(token)
        print(f"Regenerated API token: {token}")
        print(f"Store this token securely. Clients use it to authenticate with the gateway.")
    else:
        run_setup()
