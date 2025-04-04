import os
from dotenv import load_dotenv
import json
import base64
import threading
import websocket
import pyaudio
import datetime
import subprocess
import time
import queue
from websocket import WebSocketConnectionClosedException

load_dotenv()  # load .env variables

class JarvisClient:
    def __init__(self, *, api_key=None, device=None, model=None, initial_prompt=None, 
                 include_date=True, include_time=True, mode="realtime", function_calling=True, voice=None):
        """
        mode: "realtime" for audio chat (with mic streaming) or "text" for text-only chat.
        function_calling: Enable or disable function calling (e.g., run_os_command).
        voice: The voice to use for audio responses.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("API key not found in .env file.")
        self.device = device or os.getenv("DEVICE", "unknown")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini-realtime-preview-2024-12-17")
        self.initial_prompt = initial_prompt or os.getenv("INITIAL_PROMPT", "")
        self.include_date = include_date
        self.include_time = include_time
        self.mode = mode  # "realtime" or "text"
        self.function_calling = function_calling  # new flag to control function calling
        self.voice = voice or os.getenv("VOICE", "echo")  # use dynamic voice from parameter or env

        self.ws = None
        self.ws_thread = None
        self.running = False
        
        # PyAudio instance and stream placeholders (used only in realtime mode)
        self.p = pyaudio.PyAudio()
        self.output_stream = None
        self.mute_mic = False

        # Callback for text responses (used in asynchronous text mode)
        self.on_text_response = None

    def append_tools_to_message(self, message: str) -> str:
        now = datetime.datetime.now()
        additions = []
        if self.include_date:
            additions.append(f"Date: {now.strftime('%Y-%m-%d')}")
        if self.include_time:
            additions.append(f"Time: {now.strftime('%H:%M:%S')}")
        if additions:
            return f"{message} ({' | '.join(additions)})"
        else:
            return message

    def send_text_message(self, message: str, role: str = "user"):
        full_text = self.append_tools_to_message(message)
        conversation_event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": role,
                "content": [
                    {"type": "input_text", "text": full_text}
                ]
            }
        }
        print(f"DEBUG: Sending text message: {full_text}")
        self.ws.send(json.dumps(conversation_event))
        # Trigger a text-only response creation.
        response_create_event = {
            "type": "response.create",
            "response": {
                "modalities": ["text"]
            }
        }
        self.ws.send(json.dumps(response_create_event))

    def ask_sync(self, message: str, timeout=30) -> str:
        """
        Synchronously send a text message and wait until a response is received.
        Returns the response text or a timeout message.
        """
        response_queue = queue.Queue()
        original_callback = self.on_text_response

        def temp_callback(text):
            response_queue.put(text)

        self.on_text_response = temp_callback
        self.send_text_message(message)
        try:
            answer = response_queue.get(timeout=timeout)
        except queue.Empty:
            answer = "No response received within timeout."
        self.on_text_response = original_callback
        return answer

    def execute_os_command(self, command: str) -> str:
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            return result.stdout.strip() if result.stdout.strip() else result.stderr.strip()
        except Exception as e:
            return str(e)

    def on_message(self, ws, message):
        event = json.loads(message)
        event_type = event.get("type")
        print(f"DEBUG: Received event of type: {event_type}")
        
        if event_type == "response.audio.delta":
            if not self.mute_mic:
                self.mute_mic = True
                print("DEBUG: Muting microphone due to audio playback.")
            audio_chunk = event.get("delta")
            if audio_chunk and self.output_stream:
                audio_data = base64.b64decode(audio_chunk)
                self.output_stream.write(audio_data)
        
        elif event_type == "response.audio.done":
            def delayed_unmute():
                time.sleep(0.5)
                self.mute_mic = False
                print("DEBUG: Unmuting microphone after audio playback.")
            threading.Thread(target=delayed_unmute, daemon=True).start()
        
        elif event_type == "response.text.done":
            transcript = event.get("text", "")
            print(f"DEBUG: response.text.done received with transcript: {transcript}")
            if transcript and self.on_text_response:
                self.on_text_response(transcript)
        
        elif event_type == "response.content_part.done":
            part = event.get("part", {})
            print(f"DEBUG: response.content_part.done with part: {part}")
            if part.get("type") == "text":
                final_text = part.get("text", "")
                if final_text and self.on_text_response:
                    print(f"DEBUG: Sending final text from response.content_part.done: {final_text}")
                    self.on_text_response(final_text)
        
        elif event_type == "response.done":
            response = event.get("response", {})
            outputs = response.get("output", [])
            for item in outputs:
                if item.get("type") == "function_call" and item.get("name") == "run_os_command":
                    call_id = item.get("call_id")
                    arguments = item.get("arguments")
                    try:
                        args = json.loads(arguments)
                        command = args.get("command")
                    except Exception as e:
                        print("DEBUG: Error parsing function call arguments:", e)
                        command = None
                    if command:
                        result = self.execute_os_command(command)
                        output_event = {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": json.dumps({"result": result})
                            }
                        }
                        self.ws.send(json.dumps(output_event))
                        response_create_event = {"type": "response.create"}
                        self.ws.send(json.dumps(response_create_event))
                elif item.get("type") == "message":
                    text = item.get("text", "")
                    if text and self.on_text_response:
                        print(f"DEBUG: Sending text from response.done: {text}")
                        self.on_text_response(text)
        
        elif event_type == "response.output_item.done":
            item = event.get("item", {})
            print(f"DEBUG: Handling response.output_item.done with item: {item}")
            if item.get("type") == "message":
                contents = item.get("content", [])
                for content in contents:
                    if content.get("type") == "text":
                        text = content.get("text", "")
                        if text and self.on_text_response:
                            print(f"DEBUG: Sending text from response.output_item.done: {text}")
                            self.on_text_response(text)
        else:
            print("DEBUG: Unhandled event:", event)

    def on_error(self, ws, error):
        print("DEBUG: WebSocket error:", error)

    def on_close(self, ws, close_status_code, close_msg):
        print("DEBUG: WebSocket closed")
        self.running = False

    def on_open(self, ws):
        # For realtime mode, open an output audio stream
        if self.mode == "realtime":
            self.output_stream = self.p.open(format=pyaudio.paInt16,
                                              channels=1,
                                              rate=24000,
                                              output=True,
                                              frames_per_buffer=1024)
        # Include our custom instructions here so that the realtime session uses our initial prompt
        session_update = {
            "type": "session.update",
            "session": {
                "voice": self.voice,  # dynamic voice setting
                "output_audio_format": "pcm16",
                "instructions": self.initial_prompt  # override default instructions with your prompt
            }
        }
        # Only add function calling tool if enabled.
        if self.function_calling:
            session_update["session"]["tools"] = [
                {
                    "type": "function",
                    "name": "run_os_command",
                    "description": f"Execute an OS system command on the {self.device}. For example: #open -a 'Google Chrome'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The OS system command to execute."
                            }
                        },
                        "required": ["command"]
                    }
                }
            ]
            session_update["session"]["tool_choice"] = "auto"
        ws.send(json.dumps(session_update))
        # We no longer call send_initial_prompt since instructions are set in the session update.
        if self.mode == "realtime":
            threading.Thread(target=self.send_audio, daemon=True).start()

    def send_audio(self):
        mic_stream = self.p.open(format=pyaudio.paInt16,
                                 channels=1,
                                 rate=24000,
                                 input=True,
                                 frames_per_buffer=1024)
        try:
            while self.running:
                if self.mute_mic:
                    time.sleep(0.1)
                    continue
                data = mic_stream.read(1024, exception_on_overflow=False)
                encoded_data = base64.b64encode(data).decode('ascii')
                event_data = {
                    "type": "input_audio_buffer.append",
                    "audio": encoded_data
                }
                self.ws.send(json.dumps(event_data))
        except Exception as e:
            print("DEBUG: Error capturing audio:", e)
        finally:
            mic_stream.stop_stream()
            mic_stream.close()

    def start_realtime(self):
        self.running = True
        ws_url = f"wss://api.openai.com/v1/realtime?model={self.model}"
        headers = [
            f"Authorization: Bearer {self.api_key}",
            "OpenAI-Beta: realtime=v1"
        ]
        self.ws = websocket.WebSocketApp(ws_url,
                                          header=headers,
                                          on_message=self.on_message,
                                          on_error=self.on_error,
                                          on_close=self.on_close)
        self.ws.on_open = self.on_open
        self.ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.ws_thread.start()

    def stop_realtime(self):
        if self.ws:
            self.running = False
            self.ws.close()
            self.ws_thread.join()
            self.ws = None
            self.ws_thread = None

def send_text_message(self, message):
    try:
        self.ws.send(json.dumps(message))
    except WebSocketConnectionClosedException:
        print("WebSocket connection was closed. Reconnecting...")
        self.reconnect()  # Add a reconnect method if needed



        