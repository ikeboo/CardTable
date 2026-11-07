# JRPCTrigger

JSON-RPC 2.0 over TCP. Each request or batch is a UTF-8 JSON value followed by
`\n`; each response uses the same framing. Defaults: `127.0.0.1:8766`, method
`trigger`. Set `method="infer"` to use a different method name. Other methods
return `-32601`, except `rpc.discover`, which returns OpenRPC without triggering
callbacks.

```python
import cardtable as c


class App(c.Dealer):
    def setup(self):
        self.rpc = c.JRPCTrigger(callback=self.on_request)

    def on_request(self, event: c.TriggerEvent):
        event.response(
            texts={"answer": event.texts["prompt"]},
            images=event.images,  # Echo the decoded input images.
        )


if __name__ == "__main__":
    App().start()
```

Request:

```json
{"jsonrpc":"2.0","method":"trigger","params":{"texts":{"prompt":"hello"}},"id":"1"}
```

Response:

```json
{"jsonrpc":"2.0","result":{"texts":{"answer":"hello"},"images":{}},"id":"1"}
```

`event.response(texts, images, image_format="jpg")` sends an explicit result.
Images become base64 JPEG strings by default; pass `image_format="png"` for PNG.
Only `"jpg"` and `"png"` are accepted. JPEG drops alpha and uses lossy compression;
PNG preserves alpha and pixel values. Image names are preserved. Without an explicit response, completion
returns `{"texts":{"success":true},"images":{}}`; a callback exception returns
an internal error. Callback return values are ignored. Only one explicit response
is allowed. The event's internal ID identifies the request, and its JSON-RPC ID
is attached automatically. Client request IDs must be strings. Omit `id` for
a notification; notifications execute callbacks without sending a response.

`params` must be an object with required `texts: dict[str, str]` and optional
`image: dict[str, str]`. `texts` may be empty; `image` may be omitted or empty.
Other fields and positional params are rejected with `-32602` before any event
is queued. Each wire image is a base64 PNG or JPEG string. The decoded file signature
identifies the format; all images are validated and decoded before admission. Callbacks receive `event.images` as
`dict[str, np.ndarray]` and `event.texts` as `dict[str, str]`; omitted images become `{}`.
These dictionaries are also available in `event.data["params"]`. For example:

```json
{"jsonrpc":"2.0","method":"trigger","params":{"texts":{"prompt":"hello"},"image":{"input":"BASE64_PNG"}},"id":"1"}
```

The request key is singular `image`; the response key remains `images`.
Discovery describes named parameters in OpenRPC's `params`, the result in
`result.schema`, and the complete wire request in `x-request-schema`.

Separate connections and batch entries wait independently; one connection
processes successive lines in order. Dealer serializes this trigger's callbacks.
Internal event IDs isolate requests even when clients reuse the same RPC ID.

`drop_if_busy=False, q_size=10` queues requests. A full queue or busy trigger
returns `-32000`. `response_timeout=60` bounds the callback wait;
`request_timeout=30` bounds each line read and response write.
`max_request_bytes=10485760` limits a line's JSON bytes, excluding its newline;
`max_batch_size=32` limits batch entries. Timed-out or disconnected requests may
still execute already queued callbacks; an explicit response after expiry raises
`RuntimeError`. Stop closes connections, releases waiters and clears queued
messages. Callbacks already dispatched remain managed by Dealer. Start/stop are
idempotent and the trigger can restart, retaining its trigger ID.

## Client example

Start the Dealer above, then run from the repository root:

```bash
uv run python -m examples.jrpc_client
```

This sends `examples/cat.jpg` and saves returned images under
`examples/jrpc_output/`, as `response_1.jpg`, `response_2.jpg`, etc.
The client detects JPEG/PNG from the decoded file signature and uses `.jpg` or
`.png` to match the response format. The callback must explicitly
return images using `event.response(...)`, as in the example above.

```bash
uv run python -m examples.jrpc_client examples/cat.jpg --port 8766 --output-dir /tmp/jrpc-results
```

Use `--host`, `--method`, or `--timeout` to override the connection settings.
