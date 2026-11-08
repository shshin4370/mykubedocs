"""Kubernetes / Red Hat 공식문서 RAG 챗봇 (Streamlit).

실행:  streamlit run app.py
화면:  왼쪽 사이드바(새 채팅 + 채팅 기록) / 가운데 대화 / 아래 입력창 — ChatGPT 와 비슷한 구성
"""
from __future__ import annotations

import streamlit as st

import config
import rag
import storage

st.set_page_config(
    page_title="Docs Chat · Kubernetes & Red Hat",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

EXAMPLES = [
    "Pod가 CrashLoopBackOff 상태일 때 원인을 어떻게 찾나요?",
    "Deployment와 StatefulSet의 차이를 설명해 주세요",
    "How do I configure a PersistentVolumeClaim?",
    "OpenShift에서 Route와 Ingress는 어떻게 다른가요?",
]

# ---------------------------------------------------------------------------
# 스타일 (ChatGPT 다크 테마와 비슷하게)
# ---------------------------------------------------------------------------
CSS = """
<style>
.stApp { font-family: -apple-system, "Segoe UI", "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }
[data-testid="stDecoration"], footer, #MainMenu { display: none; }
[data-testid="stHeader"] { background: transparent; }

/* 가운데 대화 영역 */
.block-container { max-width: 780px; padding-top: 2rem; padding-bottom: 7rem; }

/* 메시지: 사용자는 오른쪽 말풍선, 어시스턴트는 배경 없이 본문 */
[data-testid="stChatMessage"] { background: transparent; padding: .35rem 0; gap: .75rem; }
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] { display: none; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { flex-direction: row-reverse; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
    background: #303030; border-radius: 20px; padding: .55rem 1.1rem;
    width: fit-content; max-width: 80%; flex: 0 1 auto;
}

/* 버튼은 CSS 로 전체 너비 (Streamlit 버전별 use_container_width 변경에 영향받지 않음) */
section[data-testid="stSidebar"] [data-testid="stButton"],
[class*="st-key-ex_"] [data-testid="stButton"] { width: 100%; }
section[data-testid="stSidebar"] [data-testid="stButton"] button,
[class*="st-key-ex_"] [data-testid="stButton"] button { width: 100%; }

/* 입력창 */
[data-testid="stChatInput"] { border-radius: 28px; background: #303030; border: none; }
[data-testid="stChatInput"] textarea { color: #ececec; }

/* 사이드바 */
section[data-testid="stSidebar"] { background: #171717; border-right: none; }
section[data-testid="stSidebar"] button {
    background: transparent; border: none; box-shadow: none; color: #ececec;
    justify-content: flex-start; text-align: left; padding: .45rem .7rem; border-radius: 10px;
}
section[data-testid="stSidebar"] button:hover { background: #2a2a2a; }
section[data-testid="stSidebar"] button p {
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 0;
}
.st-key-newchat button { border: 1px solid #3a3a3a; font-weight: 600; }
[class*="st-key-sessactive_"] button { background: #2f2f2f !important; }
[class*="st-key-del_"] button { color: #8e8e8e; justify-content: center; }
.side-label { color: #8e8e8e; font-size: .78rem; margin: 1.1rem 0 .3rem .7rem; }

/* 첫 화면 */
.hero { text-align: center; margin: 16vh 0 1.6rem; }
.hero h1 { font-size: 1.9rem; font-weight: 600; margin: 0 0 .45rem; }
.hero p { color: #9b9b9b; margin: 0; }
[class*="st-key-ex_"] button {
    border: 1px solid #3a3a3a; border-radius: 14px; padding: .8rem 1rem; height: auto;
    min-height: 4.2rem; text-align: left; white-space: normal; background: transparent;
}
[class*="st-key-ex_"] button:hover { background: #2a2a2a; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 상태 / 콜백
# ---------------------------------------------------------------------------
def init_state() -> None:
    if "session" not in st.session_state:
        st.session_state.session = storage.new_session()


def start_new_chat() -> None:
    st.session_state.session = storage.new_session()


def open_session(session_id: str) -> None:
    s = storage.load_session(session_id)
    if s:
        s.setdefault("messages", [])
        s.setdefault("title", "새 채팅")
        st.session_state.session = s


def remove_session(session_id: str) -> None:
    storage.delete_session(session_id)
    if st.session_state.session["id"] == session_id:
        start_new_chat()


def use_example(text: str) -> None:
    st.session_state.pending_prompt = text


@st.cache_resource(show_spinner="문서 인덱스와 모델을 불러오는 중…")
def load_bot(index_stamp: float) -> rag.RagBot:
    # index_stamp 가 바뀌면(= ingest.py 로 인덱스를 다시 만들면) 캐시가 새로 만들어집니다.
    return rag.RagBot()


# ---------------------------------------------------------------------------
# 화면 조각
# ---------------------------------------------------------------------------
def render_sources(sources: list[dict]) -> None:
    if not sources:
        return
    with st.expander(f"참고한 공식 문서 {len(sources)}건"):
        for s in sources:
            title = str(s.get("title", "")).replace("[", "(").replace("]", ")")
            st.markdown(f"- **[{s['n']}]** [{title}]({s['url']})")


def render_sidebar() -> None:
    with st.sidebar:
        st.button("＋ 새 채팅", key="newchat", on_click=start_new_chat)
        st.markdown('<div class="side-label">채팅 기록</div>', unsafe_allow_html=True)

        current_id = st.session_state.session["id"]
        sessions = storage.list_sessions()
        if not sessions:
            st.caption("아직 저장된 대화가 없습니다.")
        for s in sessions:
            prefix = "sessactive_" if s["id"] == current_id else "sess_"
            c1, c2 = st.columns([0.82, 0.18], vertical_alignment="center")
            c1.button(
                s["title"],
                key=f"{prefix}{s['id']}",
                on_click=open_session,
                args=(s["id"],),
            )
            c2.button("✕", key=f"del_{s['id']}", on_click=remove_session, args=(s["id"],), help="이 대화 삭제")

        st.divider()
        meta = rag.get_index_meta()
        if meta:
            st.caption(
                f"문서 {meta.get('num_pages', '?')}건 · 청크 {meta.get('num_chunks', '?')}개\n\n"
                f"인덱스 생성: {meta.get('created_at', '?')}"
            )
        llm_name = config.OPENAI_MODEL if config.LLM_PROVIDER == "openai" else config.ANTHROPIC_MODEL
        st.caption(f"모델: {config.LLM_PROVIDER} / {llm_name}")
        st.caption("답변 근거: kubernetes.io/docs, docs.redhat.com/en")


def render_hero() -> None:
    st.markdown(
        '<div class="hero"><h1>무엇을 도와드릴까요?</h1>'
        "<p>Kubernetes와 Red Hat 공식문서를 근거로 답변합니다.</p></div>",
        unsafe_allow_html=True,
    )


def render_examples() -> None:
    cols = st.columns(2)
    for i, text in enumerate(EXAMPLES):
        cols[i % 2].button(text, key=f"ex_{i}", on_click=use_example, args=(text,))


def handle_prompt(prompt: str, bot: rag.RagBot) -> None:
    session = st.session_state.session
    history = list(session["messages"])  # 이번 질문 이전의 대화

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("관련 공식 문서를 찾는 중…"):
                query = bot.rewrite_query(prompt, history)
                retrieval = bot.retrieve(query)
            answer = st.write_stream(bot.stream_answer(prompt, history, retrieval))
        except Exception as exc:  # API 키 오류, 네트워크 오류 등
            st.error(f"답변을 만드는 중 오류가 발생했습니다: {exc}")
            return
        render_sources(retrieval.sources)

    session["messages"] += [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": answer, "sources": retrieval.sources},
    ]
    if session.get("title", "새 채팅") == "새 채팅":
        session["title"] = storage.title_from(prompt)
    storage.save_session(session)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main() -> None:
    init_state()

    ready, message = rag.check_ready()
    if not ready:
        render_sidebar()
        render_hero()
        st.warning(message)
        st.stop()

    bot = load_bot((config.INDEX_DIR / "index.faiss").stat().st_mtime)
    session = st.session_state.session

    # 입력창은 화면 아래에 고정되므로 먼저 값을 받아도 위치는 같습니다.
    prompt = st.chat_input("Kubernetes / Red Hat 문서에 대해 질문하세요") or st.session_state.pop(
        "pending_prompt", None
    )

    if not session["messages"] and not prompt:
        render_hero()
        render_examples()
    for m in session["messages"]:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            render_sources(m.get("sources", []))

    if prompt:
        handle_prompt(prompt, bot)

    # 사이드바는 마지막에 그려야 방금 저장된 대화가 목록에 바로 나타납니다.
    render_sidebar()


main()
