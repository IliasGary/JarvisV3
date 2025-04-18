import os
import streamlit as st
from dotenv import load_dotenv, set_key
from PIL import Image
from s2s import JarvisClient  # adjust the import based on your project structure   

# Load environment variables from .env
load_dotenv()

st.set_page_config(page_title="Jarvis Chatbot", layout="centered")

# Display the logo at the top of the app centered.
logo_path = "./assets/Header.png"
if os.path.exists(logo_path):
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image(logo_path)

# Load avatar image for chat messages.
avatar_path = "./assets/full.png"
img = Image.open(avatar_path) if os.path.exists(avatar_path) else None

# Initialize chat history in session state.
if "messages" not in st.session_state:
    st.session_state.messages = []  # List of dicts: {"role": "user"/"assistant", "content": text}

# Initialize settings in session state.
if "settings" not in st.session_state:
    st.session_state.settings = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o-mini-realtime-preview-2024-12-17"),
        "INITIAL_PROMPT": os.getenv("INITIAL_PROMPT", ""),
        "DEVICE": os.getenv("DEVICE", "windows"),
        "VAD": os.getenv("VAD", "True").lower() in ("true", "1", "yes"),
        "FUNCTION_CALLING": os.getenv("FUNCTION_CALLING", "False").lower() in ("true", "1", "yes"),
        "VOICE": os.getenv("VOICE", "echo"),
        "INCLUDE_DATE": os.getenv("INCLUDE_DATE", "True").lower() in ("true", "1", "yes"),
        "INCLUDE_TIME": os.getenv("INCLUDE_TIME", "True").lower() in ("true", "1", "yes")
    }

# Initialize the text-mode Jarvis client if not already done.
if "text_client" not in st.session_state or st.session_state.text_client is None:
    st.session_state.text_client = JarvisClient(
        api_key=st.session_state.settings["OPENAI_API_KEY"],
        model=st.session_state.settings["OPENAI_MODEL"],
        initial_prompt=st.session_state.settings["INITIAL_PROMPT"],
        include_date=st.session_state.settings["INCLUDE_DATE"],
        include_time=st.session_state.settings["INCLUDE_TIME"],
        mode="text",
        function_calling=st.session_state.settings["FUNCTION_CALLING"]
    )
    st.session_state.text_client.start_realtime()  # Start the WebSocket connection

# Create three tabs: Chat, Realtime Audio, and Settings.
tabs = st.tabs(["Chat", "Realtime", "Settings"])

# --------------------- Chat Tab (tab[0]) ---------------------
with tabs[0]:
    st.title("💬 Chat with Jarvis")
    
    prompt = st.chat_input("Ask Jarvis...")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        # Synchronously send the text message and wait for a response.
        response = st.session_state.text_client.ask_sync(prompt)
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()  # Update UI immediately

    for message in st.session_state.messages:
        if message["role"] == "assistant":
            with st.chat_message("assistant", avatar=img):
                st.markdown(message["content"])
        else:
            with st.chat_message("user"):
                st.markdown(message["content"])

# --------------------- Realtime Audio Tab (tab[1]) ---------------------
with tabs[1]:
    st.header("🎙️ Realtime Audio Chat")
    if "realtime_client" in st.session_state and st.session_state.realtime_client is not None:
        if st.button("Stop Realtime Audio Chat"):
            st.session_state.realtime_client.stop_realtime()
            st.session_state.realtime_client = None
            st.success("Realtime audio chat stopped.")
            st.rerun()
    else:
        if st.button("Start Realtime Audio Chat"):
            # Create a new instance using the updated settings
            st.session_state.realtime_client = JarvisClient(
                api_key=st.session_state.settings["OPENAI_API_KEY"],
                model=st.session_state.settings["OPENAI_MODEL"],
                initial_prompt=st.session_state.settings["INITIAL_PROMPT"],
                include_date=st.session_state.settings["INCLUDE_DATE"],
                include_time=st.session_state.settings["INCLUDE_TIME"],
                mode="realtime",
                function_calling=st.session_state.settings["FUNCTION_CALLING"]
            )
            st.session_state.realtime_client.start_realtime()
            st.success("Realtime audio chat started.")
            st.rerun()
# --------------------- Settings Tab (tab[2]) ---------------------
with tabs[2]:
    st.header("Settings")
    with st.form("settings_form"):
        api_key = st.text_input("OpenAI API Key", value=st.session_state.settings["OPENAI_API_KEY"], type="password")
        model = st.selectbox(
            "OpenAI Model", 
            options=["gpt-4o-mini-realtime-preview-2024-12-17", "gpt-4o-realtime-preview-2024-12-17"],
            index=0 if st.session_state.settings["OPENAI_MODEL"] == "gpt-4o-mini-realtime-preview-2024-12-17" else 1
        )
        initial_prompt = st.text_area("Initial Prompt", value=st.session_state.settings["INITIAL_PROMPT"])
        device = st.text_input("Device", value=st.session_state.settings["DEVICE"])
        vad = st.checkbox("VAD", value=st.session_state.settings["VAD"])
        function_calling = st.checkbox("Function Calling", value=st.session_state.settings["FUNCTION_CALLING"])
        voice_options = ["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]
        voice = st.selectbox(
            "Voice", 
            options=voice_options, 
            index=voice_options.index(st.session_state.settings["VOICE"]) if st.session_state.settings["VOICE"] in voice_options else 0
        )
        include_date = st.checkbox("Include Date", value=st.session_state.settings["INCLUDE_DATE"])
        include_time = st.checkbox("Include Time", value=st.session_state.settings["INCLUDE_TIME"])
        submitted = st.form_submit_button("Save Settings")
        if submitted:
            st.session_state.settings["OPENAI_API_KEY"] = api_key
            st.session_state.settings["OPENAI_MODEL"] = model
            st.session_state.settings["INITIAL_PROMPT"] = initial_prompt
            st.session_state.settings["DEVICE"] = device
            st.session_state.settings["VAD"] = vad
            st.session_state.settings["FUNCTION_CALLING"] = function_calling
            st.session_state.settings["VOICE"] = voice
            st.session_state.settings["INCLUDE_DATE"] = include_date
            st.session_state.settings["INCLUDE_TIME"] = include_time

            env_path = ".env"
            set_key(env_path, "OPENAI_API_KEY", api_key)
            set_key(env_path, "OPENAI_MODEL", model)
            set_key(env_path, "INITIAL_PROMPT", initial_prompt)
            set_key(env_path, "DEVICE", device)
            set_key(env_path, "VAD", str(vad))
            set_key(env_path, "FUNCTION_CALLING", str(function_calling))
            set_key(env_path, "VOICE", voice)
            set_key(env_path, "INCLUDE_DATE", str(include_date))
            set_key(env_path, "INCLUDE_TIME", str(include_time))
            st.success("Settings saved to .env file. Restart the app to apply changes.")
