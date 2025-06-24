# voice_assistant_backend.py (with voice output)

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

# Setup OpenAI Client
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
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }
        .status {
            margin: 20px 0;
            padding: 10px;
            border-radius: 5px;
        }
        .listening {
            background-color: #ffeb3b;
            color: #333;
        }
        .processing {
            background-color: #2196f3;
            color: white;
        }
        .speaking {
            background-color: #4caf50;
            color: white;
        }
        button {
            background-color: #4285f4;
            color: white;
            border: none;
            padding: 15px 30px;
            font-size: 18px;
            border-radius: 5px;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        button:hover {
            background-color: #3367d6;
        }
    </style>
</head>
<body>
    <h1>Voice Assistant</h1>
    <div id="status"></div>
    <form action="/activate" method="post">
        <button type="submit">🎤 Activate Assistant</button>
    </form>
    <div id="conversation" style="margin-top: 20px;"></div>
    
    <script>
        document.querySelector('form').addEventListener('submit', function(e) {
            e.preventDefault();
            const statusDiv = document.getElementById('status');
            statusDiv.className = 'status listening';
            statusDiv.textContent = '🎤 Listening... Speak now!';
            
            fetch('/activate', { method: 'POST' })
                .then(response => response.text())
                .then(html => {
                    document.getElementById('conversation').innerHTML = html;
                    statusDiv.className = '';
                    statusDiv.textContent = '';
                    
                    // Auto-play the audio response
                    const audio = document.querySelector('audio');
                    if (audio) {
                        audio.play();
                    }
                })
                .catch(error => {
                    statusDiv.className = '';
                    statusDiv.textContent = '❌ Error: ' + error.message;
                });
        });
    </script>
</body>
</html>
'''

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_PAGE)

# Speech Recognition
def recognize_speech():
    config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    config.speech_recognition_language = "en-US"
    
    # Use microphone input
    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
    recognizer = speechsdk.SpeechRecognizer(speech_config=config, audio_config=audio_config)
    
    print("Listening...")
    result = recognizer.recognize_once_async().get()
    
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print(f"Recognized: {result.text}")
        return result.text
    elif result.reason == speechsdk.ResultReason.NoMatch:
        print("No speech could be recognized")
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation = speechsdk.CancellationDetails.from_result(result)
        print(f"Speech Recognition canceled: {cancellation.reason}")
    
    return ""

# Persistent conversation history
conversation_history = [
    {"role": "system", "content": "You are a helpful assistant."}
]

def get_reply(user_input):
    conversation_history.append({"role": "user", "content": user_input})
    
    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=conversation_history,
            temperature=0.7,
            max_tokens=250,
        )
        assistant_reply = response.choices[0].message.content
        conversation_history.append({"role": "assistant", "content": assistant_reply})
        return assistant_reply
    except Exception as e:
        print(f"Error getting OpenAI response: {str(e)}")
        return "I'm having trouble thinking right now. Please try again later."

# Text-to-Speech with playback
def text_to_speech(text, filename="static/reply.wav"):
    try:
        config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
        config.speech_synthesis_voice_name = "en-US-JennyNeural"
        audio_config = speechsdk.audio.AudioOutputConfig(filename=filename)
        
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=audio_config)
        result = synthesizer.speak_text_async(text).get()
        
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"Speech synthesized to {filename}")
            return filename
        else:
            print(f"Speech synthesis failed: {result.reason}")
            return None
    except Exception as e:
        print(f"Error in text-to-speech: {str(e)}")
        return None

# Serve static audio directly
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# Flask route to trigger the assistant
@app.route('/activate', methods=['POST'])
def activate():
    # Step 1: Recognize user speech
    user_input = recognize_speech()
    if not user_input:
        return render_template_string("<div class='status'>❌ Speech not recognized. Please try again.</div>")
    
    print(f"User said: {user_input}")
    
    # Step 2: Get AI response
    reply = get_reply(user_input)
    print(f"Assistant replied: {reply}")
    
    # Step 3: Convert to speech
    audio_path = text_to_speech(reply)
    
    # Notify Unity client
    if unity_ws:
        asyncio.run(unity_ws.send(json.dumps({
            "type": "reply",
            "text": reply,
            "audio_url": f"http://localhost:5000/static/reply.wav"
        })))
    
    # Return HTML with conversation and audio player
    return render_template_string("""
        <div class="user-message">
            <strong>You:</strong> {{ user_input }}
        </div>
        <div class="assistant-message">
            <strong>Assistant:</strong> {{ reply }}
        </div>
        {% if audio_path %}
        <audio controls autoplay style="margin-top: 15px;">
            <source src="/static/reply.wav" type="audio/wav">
            Your browser does not support the audio element.
        </audio>
        {% endif %}
    """, user_input=user_input, reply=reply, audio_path=audio_path)

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
        app.run(port=5000, threaded=True)

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # WebSocket server
    async def start_websocket():
        async with websockets.serve(unity_socket, 'localhost', 8765):
            print("WebSocket server started on ws://localhost:8765")
            await asyncio.Future()  # Run forever

    asyncio.run(start_websocket())
