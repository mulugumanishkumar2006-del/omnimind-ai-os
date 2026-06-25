import os
import streamlit as st
from frontend.components import widgets

# Configure Streamlit Page
st.set_page_config(
    page_title="OmniMind AI OS",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Base URL for backend FastAPI service
BACKEND_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")

# Load Custom CSS stylesheet
css_path = os.path.join(os.path.dirname(__file__), "assets", "custom.css")
if os.path.exists(css_path):
    try:
        with open(css_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"Could not load custom CSS: {str(e)}")

# Sidebar Header & Navigation
st.sidebar.markdown("""
<div style='text-align: center; margin-bottom: 1.5rem;'>
    <h1 style='margin-bottom: 0px;'>🌌 OmniMind AI OS</h1>
    <span style='color: #888888; font-size: 0.95rem;'>Intelligent Unified Workspace</span>
</div>
""", unsafe_allow_html=True)

# Select Workspace Tab
module_selection = st.sidebar.radio(
    "Modules Workspace",
    [
        "🧠 Memory Vault",
        "📋 Task Intelligence",
        "🕸️ Knowledge Graph",
        "🤖 Agent Framework",
        "🎨 Prompt Studio",
        "🔍 Intelligent Search",
        "🎙️ Meeting Intelligence",
        "🎓 Learning Hub",
        "🔌 Model Router",
        "🛡️ Security Center",
        "🔄 Self-Improvement",
        "📊 Operations Center"
    ],
    index=0
)

st.sidebar.divider()

# Sidebar Global Settings
st.sidebar.subheader("System Configurations")
st.sidebar.caption("Provide key tokens to enable production routes. Defaults to Simulation Mode.")

# Input fields for API keys (can also load from environment)
openai_key = st.sidebar.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
anthropic_key = st.sidebar.text_input("Claude API Key", type="password", value=os.getenv("CLAUDE_API_KEY", ""))
gemini_key = st.sidebar.text_input("Gemini API Key", type="password", value=os.getenv("GEMINI_API_KEY", ""))
deepseek_key = st.sidebar.text_input("DeepSeek API Key", type="password", value=os.getenv("DEEPSEEK_API_KEY", ""))

if st.sidebar.button("Save Configurations"):
    os.environ["OPENAI_API_KEY"] = openai_key
    os.environ["CLAUDE_API_KEY"] = anthropic_key
    os.environ["GEMINI_API_KEY"] = gemini_key
    os.environ["DEEPSEEK_API_KEY"] = deepseek_key
    st.sidebar.success("Tokens cached in memory.")
    st.rerun()

# Module Router routing map
if module_selection == "🧠 Memory Vault":
    widgets.render_memory_vault(BACKEND_URL)
elif module_selection == "📋 Task Intelligence":
    widgets.render_task_workspace(BACKEND_URL)
elif module_selection == "🕸️ Knowledge Graph":
    widgets.render_graph_viewer(BACKEND_URL)
elif module_selection == "🤖 Agent Framework":
    widgets.render_agent_viewer(BACKEND_URL)
elif module_selection == "🎨 Prompt Studio":
    widgets.render_prompt_studio(BACKEND_URL)
elif module_selection == "🔍 Intelligent Search":
    widgets.render_search_interface(BACKEND_URL)
elif module_selection == "🎙️ Meeting Intelligence":
    widgets.render_meeting_room(BACKEND_URL)
elif module_selection == "🎓 Learning Hub":
    widgets.render_learning_dashboard(BACKEND_URL)
elif module_selection == "🔌 Model Router":
    widgets.render_router_dashboard(BACKEND_URL)
elif module_selection == "🛡️ Security Center":
    widgets.render_security_dashboard(BACKEND_URL)
elif module_selection == "🔄 Self-Improvement":
    widgets.render_improvement_dashboard(BACKEND_URL)
elif module_selection == "📊 Operations Center":
    widgets.render_analytics_dashboard(BACKEND_URL)
