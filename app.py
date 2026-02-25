import streamlit as st
import requests
from dotenv import load_dotenv
import os

load_dotenv()

API_URL = os.getenv("API_URL")
APP_PASSWORD = os.getenv("APP_PASSWORD")

st.set_page_config(
    page_title="Titanic Dataset Chat Agent",
    page_icon="🚢",
    layout="centered",
)

st.markdown(
    """
    <style>
    .stApp {
        max-width: 800px;
        margin: 0 auto;
    }
    .chart-container {
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        padding: 8px;
        margin-top: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 Titanic Dataset Chat Agent")
    st.caption("To prevent api abuse, i added password.")
    st.caption("HINT : YOUR ORGANIZATION (no space , all small characters, or check assessment submission)")

    with st.form("password_form"):
        password = st.text_input("Password", type="password", placeholder="Enter password…")
        submitted = st.form_submit_button("Unlock", use_container_width=True)

        if submitted:
            if password == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Incorrect password. Please try again.")

    st.stop()  # Block everything below until authenticated

# ---------------------------------------------------------------------------
# Main app (only accessible after authentication)
# ---------------------------------------------------------------------------
st.title("🚢 Titanic Dataset Chat Agent")
st.caption(
    "Ask me anything about the Titanic passengers — I can crunch numbers and draw charts!"
)

if "messages" not in st.session_state:
    st.session_state.messages = []


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("chart"):
            st.image(
                f"{API_URL}/charts/{msg['chart']}",
                use_column_width=True,
            )

if prompt := st.chat_input("Ask about the Titanic dataset…"):
    # Show user message immediately
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call the FastAPI backend
    with st.chat_message("assistant"):
        with st.spinner("Analyzing the dataset…"):
            try:
                resp = requests.post(
                    f"{API_URL}/chat",
                    json={"question": prompt},
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()

                answer = data.get("answer", "Sorry, I couldn't process that.")
                chart = data.get("chart")

                st.markdown(answer)

                if chart:
                    st.image(
                        f"{API_URL}/charts/{chart}",
                        use_column_width=True,
                    )

                st.session_state.messages.append(
                    {"role": "assistant", "content": answer, "chart": chart}
                )

            except requests.exceptions.ConnectionError:
                err = "⚠️ Cannot reach the backend. Make sure the FastAPI server is running (`uvicorn main:app --reload`)."
                st.error(err)
                st.session_state.messages.append(
                    {"role": "assistant", "content": err}
                )
            except Exception as e:
                err = f"⚠️ Error: {e}"
                st.error(err)
                st.session_state.messages.append(
                    {"role": "assistant", "content": err}
                )
