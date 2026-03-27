from __future__ import annotations

import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from snack_app.catalog import cart_recommendations, checkout_summary, discovery_sections, filter_snacks

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / 'frontend'


class SnackAppHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict[str, object] | list[object], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, relative_path: str) -> None:
        file_path = (FRONTEND_ROOT / relative_path).resolve()
        if FRONTEND_ROOT not in file_path.parents and file_path != FRONTEND_ROOT:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = file_path.read_bytes()
        content_type, _ = mimetypes.guess_type(str(file_path))
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', content_type or 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {'/', '/index.html'}:
            self._send_static('index.html')
            return
        if parsed.path == '/app.js':
            self._send_static('app.js')
            return
        if parsed.path == '/styles.css':
            self._send_static('styles.css')
            return
        if parsed.path == '/api/discovery':
            self._send_json(discovery_sections())
            return
        if parsed.path == '/api/snacks':
            params = parse_qs(parsed.query)
            payload = filter_snacks(
                query=params.get('query', [''])[0],
                category=params.get('category', [''])[0],
                flavor=params.get('flavor', [''])[0],
                scene=params.get('scene', [''])[0],
                max_price=float(params['max_price'][0]) if params.get('max_price') else None,
                healthy_only=params.get('healthy_only', ['false'])[0].lower() == 'true',
                sort_by=params.get('sort_by', ['smart'])[0],
            )
            self._send_json({'items': payload})
            return
        if parsed.path == '/api/recommendations':
            params = parse_qs(parsed.query)
            cart_ids = [item for item in params.get('cart', [''])[0].split(',') if item]
            self._send_json({'items': cart_recommendations(cart_ids)})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != '/api/cart/summary':
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get('Content-Length', '0'))
        raw_body = self.rfile.read(content_length) if content_length else b'{}'
        try:
            payload = json.loads(raw_body.decode('utf-8'))
        except json.JSONDecodeError:
            self._send_json({'error': 'invalid json'}, status=HTTPStatus.BAD_REQUEST)
            return
        lines = payload.get('lines', []) if isinstance(payload, dict) else []
        coupon_code = payload.get('coupon_code', '') if isinstance(payload, dict) else ''
        self._send_json(checkout_summary(lines, coupon_code=coupon_code))

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    host = os.getenv('SNACK_APP_HOST', '127.0.0.1')
    port = int(os.getenv('SNACK_APP_PORT', '8765'))
    server = ThreadingHTTPServer((host, port), SnackAppHandler)
    print(f'Snack app is running at http://{host}:{port}')
    server.serve_forever()


if __name__ == '__main__':
    main()
