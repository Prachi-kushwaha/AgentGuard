"""Local HTTP provider for deterministic integration testing.

Returns HTTP 503 twice, then a successful JSON shipping-rate response.
This server is only a test fixture/demo provider, not a production carrier.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

class ProviderState:
    def __init__(self, failures_before_success=2):
        self.failures_before_success = failures_before_success
        self.request_count = 0
        self.lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    state = None

    def do_POST(self):
        if self.path != "/rates":
            self.send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")

        with self.state.lock:
            self.state.request_count += 1
            request_number = self.state.request_count

        if request_number <= self.state.failures_before_success:
            self.send_json(503, {"error": "temporarily unavailable"})
            return

        self.send_json(200, {
            "request": body,
            "rates": [
                {"carrier": "ExampleCarrier", "service": "Standard", "amount": 125.00, "currency": "INR", "delivery_days": 3},
                {"carrier": "ExampleCarrier", "service": "Express", "amount": 240.00, "currency": "INR", "delivery_days": 1}
            ]
        })

    def send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        # Keep standard HTTP server logs concise.
        print("[local-provider]", format % args)

def create_server(host="127.0.0.1", port=8089, failures_before_success=2):
    state = ProviderState(failures_before_success)
    handler = type("StatefulHandler", (Handler,), {"state": state})
    server = ThreadingHTTPServer((host, port), handler)
    return server, state

if __name__ == "__main__":
    server, state = create_server()
    print(f"Local test provider listening on http://{server.server_address[0]}:{server.server_address[1]}")
    print(f"It will fail {state.failures_before_success} times with HTTP 503, then succeed.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
