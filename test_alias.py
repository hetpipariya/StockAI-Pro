import asyncio
import websockets
from fastapi import FastAPI, WebSocket
import uvicorn
import threading

app = FastAPI()

@app.websocket("/ws1")
async def ws1(ws: WebSocket):
    await ws.accept()
    await ws.send_text("Success!")
    await ws.close()

@app.websocket("/ws2")
async def ws2(ws: WebSocket):
    await ws1(ws)

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8010)

async def test_client():
    await asyncio.sleep(2)
    try:
        async with websockets.connect("ws://127.0.0.1:8010/ws2") as websocket:
            response = await websocket.recv()
            print(f"CLIENT RECEIVED: {response}")
    except Exception as e:
        print(f"CLIENT ERROR: {e}")

if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    asyncio.run(test_client())
