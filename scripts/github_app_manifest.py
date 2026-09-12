"""One-shot helper to register the Mergency GitHub App via GitHub's manifest flow.

Usage:
    python scripts/github_app_manifest.py --hook-url https://example.ngrok.io/webhooks/github
"""
import argparse
import json
import secrets
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

CALLBACK_PORT = 8000
CALLBACK_PATH = "/setup/callback"


def _build_manifest(hook_url: str, app_name: str) -> dict:
    return {
        "name": app_name,
        "url": "https://github.com/mergency",
        "hook_attributes": {"url": hook_url},
        "redirect_url": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
        "public": False,
        "default_permissions": {
            "contents": "read",
            "checks": "read",
            "pull_requests": "write",
        },
        "default_events": [
            "installation",
            "installation_repositories",
            "push",
            "pull_request",
            "check_run",
        ],
    }


def _render_redirect_page(manifest: dict, state: str) -> bytes:
    manifest_json = json.dumps(manifest)
    return f"""<!doctype html>
<html>
<body onload="document.forms[0].submit()">
  <form method="post" action="https://github.com/settings/apps/new?state={state}">
    <input type="hidden" name="manifest" value='{manifest_json}'>
  </form>
</body>
</html>""".encode()


def _exchange_code(code: str) -> dict:
    request = urllib.request.Request(
        f"https://api.github.com/app-manifests/{code}/conversions",
        method="POST",
        headers={"Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


class _CallbackHandler(BaseHTTPRequestHandler):
    manifest: dict = {}
    state: str = ""
    result: dict | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/":
            body = _render_redirect_page(self.manifest, self.state)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == CALLBACK_PATH:
            query = parse_qs(parsed.query)
            if query.get("state", [None])[0] != self.state:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"State mismatch, aborting.")
                _CallbackHandler.result = {}
                return

            code = query["code"][0]
            try:
                _CallbackHandler.result = _exchange_code(code)
            except urllib.error.HTTPError as error:
                self.send_response(502)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"GitHub rejected the manifest exchange, check your terminal.")
                print(f"\nGitHub returned an error: {error.code} {error.read().decode()}")
                _CallbackHandler.result = {}
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"App created, check your terminal, you can close this tab.")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook-url", required=True, help="Public URL GitHub should deliver webhooks to")
    parser.add_argument("--app-name", default=f"mergency-dev-{secrets.token_hex(4)}")
    args = parser.parse_args()

    _CallbackHandler.manifest = _build_manifest(args.hook_url, args.app_name)
    _CallbackHandler.state = secrets.token_urlsafe(16)

    server = HTTPServer(("0.0.0.0", CALLBACK_PORT), _CallbackHandler)
    print(f"Open http://localhost:{CALLBACK_PORT}/ in your browser to create the GitHub App.")

    while _CallbackHandler.result is None:
        server.handle_request()

    result = _CallbackHandler.result
    if not result:
        sys.exit(1)

    print("\nGitHub App created. Paste this into your .env:\n")
    print(f"MERGENCY_GITHUB_APP_ID={result['id']}")
    print(f"MERGENCY_GITHUB_WEBHOOK_SECRET={result['webhook_secret']}")
    pem_escaped = result["pem"].replace("\n", "\\n")
    print(f"MERGENCY_GITHUB_PRIVATE_KEY={pem_escaped}")


if __name__ == "__main__":
    main()
