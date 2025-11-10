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

# --- DEBUG BLOCK (temporary) ---
import json, importlib, sys, requests

def safe_version(pkg):
    try:
        return importlib.metadata.version(pkg)
    except Exception:
        try:
            m = importlib.import_module(pkg)
            return getattr(m, "__version__", "unknown")
        except Exception:
            return "not-installed"

st.write("DEBUG: python_version", sys.version.split()[0])
st.write("DEBUG: streamlit_version", safe_version("streamlit"))
st.write("DEBUG: openai_package_version", safe_version("openai"))

# Check presence of secrets (boolean only)
has_key = bool((st.secrets.get("OPENAI_API_KEY") if hasattr(st, "secrets") else None) or os.getenv("OPENAI_API_KEY"))
has_assistant = bool((st.secrets.get("OPENAI_ASSISTANT_MODEL") if hasattr(st, "secrets") else None) or os.getenv("OPENAI_ASSISTANT_MODEL"))
st.write("DEBUG: has_openai_key?", has_key)
st.write("DEBUG: has_assistant_id?", has_assistant)

# If we have an assistant id and key, probe the Assistants endpoint and show the HTTP status + body
if has_key and has_assistant:
    key = (st.secrets.get("OPENAI_API_KEY") if hasattr(st, "secrets") else None) or os.getenv("OPENAI_API_KEY")
    aid = (st.secrets.get("OPENAI_ASSISTANT_MODEL") if hasattr(st, "secrets") else None) or os.getenv("OPENAI_ASSISTANT_MODEL")
    try:
        url = f"https://api.openai.com/v1/assistants/{aid}"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        # optional: if you need to test org header, set OPENAI_ORG in secrets/env and this will include it
        org = (st.secrets.get("OPENAI_ORG") if hasattr(st, "secrets") else None) or os.getenv("OPENAI_ORG")
        if org:
            headers["OpenAI-Organization"] = org
        resp = requests.get(url, headers=headers, timeout=10)
        st.write("DEBUG: probe_url", url)
        st.write("DEBUG: status_code", resp.status_code)
        # print JSON body (safe)
        try:
            st.write("DEBUG: body", resp.json())
        except Exception:
            st.write("DEBUG: body (text)", resp.text[:1000])
    except Exception as e:
        st.write("DEBUG: probe failed:", str(e))
else:
    st.write("DEBUG: missing key or assistant id; skipping probe")
# --- END DEBUG BLOCK ---

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
        used_assistant = True
    except Exception as e:
        err = str(e).lower()
        # If OpenAI requires the beta header (invalid_beta) or assistant not found,
        # fall back to a regular chat model so the app remains usable.
        if "invalid_beta" in err or "does not exist" in err or "model_not_found" in err:
            used_assistant = False
            st.warning("Assistants API not available in this environment; falling back to a chat model.")
            # build messages for the chat API
            messages_for_chat = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages
            ]
            fallback_model = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-3.5-turbo")
            try:
                # Non-streaming simple call to create a single completion
                resp = client.chat.completions.create(
                    model=fallback_model,
                    messages=messages_for_chat,
                    stream=False,
                )
                # The exact access pattern may vary slightly depending on client version.
                # Try common attributes returned by newer SDKs:
                if hasattr(resp, "choices") and len(resp.choices) > 0:
                    text = getattr(resp.choices[0], "message", {}).get("content", None) \
                           or getattr(resp.choices[0], "delta", {}).get("content", "") \
                           or getattr(resp.choices[0], "text", "")
                    # If it's an object, stringify fallback
                    if isinstance(text, (list, dict)):
                        text = str(text)
                    st.markdown(text)
                    st.session_state.messages.append({"role": "assistant", "content": text})
                    # Skip the thread polling below since we used a fallback.
                    continue
                else:
                    # Try another common shape
                    body_text = getattr(resp, "text", None) or str(resp)
                    st.markdown(body_text)
                    st.session_state.messages.append({"role": "assistant", "content": body_text})
                    continue
            except Exception as e2:
                st.error(f"Fallback chat model call failed: {e2}")
                st.stop()
        else:
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