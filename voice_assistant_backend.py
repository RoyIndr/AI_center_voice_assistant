# voice_assistant_backend.py (with working audio + multi-turn memory)

import os
import json
import asyncio
import websockets
from flask import Flask, request, render_template_string, send_from_directory
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Azure Keys and Config
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Setup OpenAI Client (new SDK)
client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version="2023-05-15",
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)

app = Flask(__name__)
app.static_folder = 'static'
unity_ws = None  # Will hold WebSocket connection to Unity

# Create static folder if not exists
if not os.path.exists("static"):
    os.makedirs("static")

# HTML Template
HTML_PAGE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>3D Avatar Voice Assistant</title>
</head>
<body>
    <h1>Voice Assistant</h1>
    <form action="/activate" method="post">
        <button type="submit">🎤 Speak Now</button>
    </form>
</body>
</html>
'''

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_PAGE)

# Speech Recognition
def recognize_speech():
    config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    recognizer = speechsdk.SpeechRecognizer(speech_config=config)
    print("Listening...")
    result = recognizer.recognize_once()
    print("Recognition result:", result.text)
    return result.text if result.reason == speechsdk.ResultReason.RecognizedSpeech else ""

# Persistent conversation history
conversation_history = [
    {"role": "system", "content": "You are a helpful assistant."}
]

def get_reply(user_input):
    conversation_history.append({"role": "user", "content": user_input})
    response = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=conversation_history,
        temperature=0.7,
        max_tokens=200,
    )
    assistant_reply = response.choices[0].message.content
    conversation_history.append({"role": "assistant", "content": assistant_reply})
    return assistant_reply

# Text-to-Speech
def text_to_speech(text, filename="static/reply.wav"):
    config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    config.speech_synthesis_voice_name = "en-US-JennyNeural"
    audio_config = speechsdk.audio.AudioOutputConfig(filename=filename)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=audio_config)
    result = synthesizer.speak_text_async(text).get()
    return filename if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted else None

# Serve static audio directly
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# Flask route to trigger the assistant via form POST
@app.route('/activate', methods=['POST'])
def activate():
    user_input = recognize_speech()
    if not user_input:
        return render_template_string("<h2>❌ Speech not recognized. Please try again.</h2><a href='/'>⬅ Back</a>")

    print(f"User said: {user_input}")
    reply = get_reply(user_input)
    print(f"Assistant replied: {reply}")

    audio_path = text_to_speech(reply)
    if unity_ws:
        asyncio.run(unity_ws.send(json.dumps({"type": "reply", "text": reply})))

    return render_template_string(f"""
        <h2>✅ You said: <em>{user_input}</em></h2>
        <h3>🤖 Assistant replied: <em>{reply}</em></h3>
        <audio controls autoplay>
            <source src="/static/reply.wav" type="audio/wav">
        </audio>
        <br><a href='/'>⬅ Back</a>
    """)

# WebSocket server to talk with Unity
async def unity_socket(websocket, path):
    global unity_ws
    unity_ws = websocket
    print("Unity connected via WebSocket.")
    try:
        while True:
            await asyncio.sleep(1)  # Idle loop
    except:
        print("Unity disconnected.")
        unity_ws = None

# Entrypoint
if __name__ == '__main__':
    import threading

    # Start Flask in a separate thread
    def run_flask():
        app.run(port=5000)

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    # WebSocket server
    async def start_websocket():
        async with websockets.serve(unity_socket, 'localhost', 8765):
            print("WebSocket server started on ws://localhost:8765")
            while True:
                await asyncio.sleep(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_websocket())
