import os
import time
import streamlit as st
from openai import OpenAI

# --- UI SETUP ---
st.title("💬 Chatbot (Assistants API)")
st.write(
    "This chatbot uses your custom OpenAI Assistant via the Assistants API (v2). "
    "Enter your API key to start chatting."
)

# --- AUTHENTICATION ---
openai_api_key = (
    st.secrets.get("OPENAI_API_KEY") if hasattr(st, "secrets") else None
) or os.getenv("OPENAI_API_KEY") or st.text_input("🔑 OpenAI API Key", type="password")

if not openai_api_key:
    st.info("Please add your OpenAI API key to continue.", icon="🗝️")
    st.stop()

client = OpenAI(api_key=openai_api_key)

# --- ASSISTANT CONFIG ---
# Prefer Streamlit secrets, then environment variable.
assistant_id = (
    st.secrets.get("OPENAI_ASSISTANT_MODEL") if hasattr(st, "secrets") else None
) or os.getenv("OPENAI_ASSISTANT_MODEL")

if not assistant_id:
    st.error(
        "Assistant ID is not configured. "
        "Set OPENAI_ASSISTANT_MODEL in Streamlit Cloud Secrets or as an environment variable."
    )
    st.stop()

# --- SESSION STATE ---
if "thread_id" not in st.session_state:
    # Create a conversation thread once per session
    thread = client.beta.threads.create()
    st.session_state.thread_id = thread.id
    st.session_state.messages = []

# --- DISPLAY CHAT HISTORY ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- CHAT INPUT ---
if prompt := st.chat_input("Say something..."):
    # Store and display user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Add user message to thread
    try:
        client.beta.threads.messages.create(
            thread_id=st.session_state.thread_id,
            role="user",
            content=prompt
        )
    except Exception as e:
        st.error(f"Failed to add message to thread: {e}")
        st.stop()

    # Create a run for your Assistant (use configured assistant_id)
    try:
        run = client.beta.threads.runs.create(
            thread_id=st.session_state.thread_id,
            assistant_id=assistant_id
        )
    except Exception as e:
        st.error(f"Failed to start assistant run: {e}")
        st.stop()

    # Wait for completion (polling)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            while True:
                try:
                    run_status = client.beta.threads.runs.retrieve(
                        thread_id=st.session_state.thread_id,
                        run_id=run.id
                    )
                except Exception as e:
                    st.error(f"Failed to retrieve run status: {e}")
                    st.stop()

                if run_status.status == "completed":
                    break
                elif run_status.status in ["failed", "expired"]:
                    st.error(f"Run failed with status: {run_status.status}")
                    st.stop()
                time.sleep(1)

            # Retrieve messages from the thread
            try:
                messages = client.beta.threads.messages.list(thread_id=st.session_state.thread_id)
            except Exception as e:
                st.error(f"Failed to list thread messages: {e}")
                st.stop()

            # The last assistant message (if any)
            last_msg = next((m for m in messages.data if m.role == "assistant"), None)

            if last_msg:
                # The structure returned by the SDK may be nested; this follows prior logic.
                try:
                    response = last_msg.content[0].text.value
                except Exception:
                    # Fallback: try to stringify the content
                    response = str(last_msg)
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})