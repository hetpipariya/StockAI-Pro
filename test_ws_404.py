from fastapi import FastAPI, WebSocket
import uvicorn

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    await ws.send_text("Hello")
    await ws.close()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8009)
