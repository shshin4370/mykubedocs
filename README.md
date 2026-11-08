# Kubernetes 공식문서 RAG 챗봇

Kubernetes 공식문서(`kubernetes.io/docs`)**만**을 근거로 답변하는 챗봇입니다.
LangChain으로 RAG 파이프라인을 만들고, Streamlit으로 ChatGPT와 비슷한 화면을 로컬에서 실행합니다.
외부 Vector DB 서버는 필요 없습니다. (로컬 FAISS 인덱스 사용)

> 수업 자료 `2일차.ipynb` 의 RAG 구성(OpenAI 임베딩 `text-embedding-3-small` + FAISS + LCEL 프롬프트 + `gpt-5-nano`, `.env` 로 API 키 관리)을
> 그대로 이어받아, 공식문서 크롤링·대화 세션·웹 UI로 확장한 프로젝트입니다.
> 제작 과정과 설계 이유는 [MYPLAN.md](MYPLAN.md)에 정리되어 있습니다.

---

## 주요 기능

- **공식문서 기반 답변** — 검색된 문서 조각만 근거로 답하고, 근거가 없으면 "찾지 못했다"고 안내합니다. 답변 문장 뒤에 `[1]`, `[2]` 출처 번호가 붙고, 아래에서 원문 링크를 볼 수 있습니다.
- **세션형 대화 기억** — 대화는 세션 단위로 저장되어 앱을 껐다 켜도 남아 있습니다. 사이드바에서 과거 대화를 다시 열거나 삭제할 수 있고, 같은 세션 안에서는 앞선 대화를 이어서 이해합니다. ("그럼 그건 어떻게 해?" 같은 후속 질문 가능)
- **ChatGPT 스타일 화면** — 왼쪽 사이드바(새 채팅 · 채팅 기록), 가운데 대화, 아래 입력창, 실시간 스트리밍 출력.
- **한국어 질문 ↔ 영어 문서** — 질문을 대화 맥락이 반영된 영어 검색어로 바꿔 검색하고, 답변은 질문한 언어로 합니다.
- **공식문서만 수집** — 허용된 도메인·경로 안의 링크만 따라가며, robots.txt를 지키고 요청 사이에 지연을 둡니다.

## 실행 화면

<!-- 앱을 실행한 뒤 화면을 캡처해 docs/screenshot.png 로 저장하고, 아래 줄의 주석을 해제하세요. -->
<!-- ![실행 화면](docs/screenshot.png) -->

## 동작 방식

```
[1회: 인덱스 생성]  python ingest.py
  시작 URL → 크롤링(허용 규칙·robots·캐시) → 본문 추출 → 청크 분할 → 임베딩 → FAISS 저장

[채팅]  streamlit run app.py
  질문 → (대화 기록 반영) 검색어 재작성 → FAISS MMR 검색 → 컨텍스트 구성
       → LLM 답변 스트리밍(출처 인용) → 세션 JSON 저장
```

---

## 사용 방법

### 1. 준비 (Python 3.10 이상 권장)

수업에서 쓰는 conda 환경(`py310`)이 있다면 그대로 사용하면 됩니다.

```bash
conda activate py310
cd k8s-redhat-rag-chatbot
pip install -r requirements.txt
```

conda 가 없다면 venv 를 사용하세요.

```bash
cd k8s-redhat-rag-chatbot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 환경 설정

```bash
cp .env.example .env               # Windows: copy .env.example .env
```

`.env` 를 열어 사용할 모델의 API 키를 입력합니다. 기본값은 `2일차.ipynb` 와 같은 OpenAI 구성(답변 `gpt-5-nano`, 임베딩 `text-embedding-3-small`)입니다. `OPENAI_MODEL` 로 `gpt-4o-mini` 등 다른 모델을 고를 수 있습니다.

| 설정 | 값 | 설명 |
|---|---|---|
| `LLM_PROVIDER` | `openai` / `anthropic` | 답변을 만드는 모델 |
| `EMBEDDING_PROVIDER` | `openai` / `huggingface` | 임베딩 모델 (`huggingface` 는 API 키 없이 로컬 실행, `requirements.txt` 의 선택 항목 설치 필요) |

> 임베딩 설정은 **인덱스를 만들 때와 앱을 실행할 때 같아야** 합니다. 다르면 앱이 안내 메시지를 보여줍니다.

### 3. 문서 인덱스 만들기 (처음 한 번)

```bash
python ingest.py                   # 기본: 사이트당 최대 200페이지, 링크 깊이 3
python ingest.py --max-pages 30    # 빠르게 시험해 보고 싶을 때
```

- 받은 페이지는 `data/raw/` 에 캐시되어 다시 실행해도 재다운로드하지 않습니다. 새로 받으려면 `--refresh`.
- 크롤링 없이 캐시로 인덱스만 다시 만들려면 `--reindex-only` (임베딩 모델을 바꾼 경우 등).
- 중간에 `Ctrl+C` 로 멈추면 그때까지 모은 페이지로 인덱스를 만듭니다.
- 특정 제품 문서를 더 넣으려면 시작 URL을 추가하세요. 허용 범위(`docs.redhat.com/en`) 안의 주소여야 합니다.

```bash
python ingest.py --seed <docs.redhat.com/en 아래의 문서 주소>
# 또는 .env 의 EXTRA_SEEDS=주소1,주소2
```

### 4. 챗봇 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 이 열립니다.

- **새 채팅** : 사이드바 위쪽 버튼
- **과거 대화 열기 / 삭제** : 사이드바의 채팅 기록 (`✕` 로 삭제)
- **출처 확인** : 답변 아래 "참고한 공식 문서" 펼치기

대화는 `data/sessions/*.json` 에 저장됩니다. 인덱스를 다시 만들면 앱을 재시작하지 않아도 새 인덱스가 반영됩니다.

### 5. 테스트 (선택)

네트워크와 API 키 없이 실행되는 단위 테스트입니다. (크롤링 허용 규칙, 본문 추출, 크롤러 동작, 세션 저장)

```bash
python -m unittest discover -s tests -v
```

---

## 수집 범위 바꾸기

수집 범위는 `config.py` 의 `ALLOWED_RULES` 로 제한됩니다. 이 규칙에 맞지 않는 주소는 링크가 있어도 방문하지 않습니다.

```python
ALLOWED_RULES = [
    {"host": "kubernetes.io",    "path_prefix": "/docs"},
    {"host": "docs.redhat.com",  "path_prefix": "/en"},
]
```

"공식문서만 사용" 조건 때문에 기본값은 위 두 곳으로 한정했습니다. 다른 공식 사이트를 포함하려면 규칙을 직접 추가하세요.

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 웹 UI | Streamlit (사용자 CSS로 ChatGPT 스타일 구성, `st.chat_message` · `st.chat_input` · `st.write_stream`) |
| RAG 프레임워크 | LangChain (`langchain-core` LCEL: `ChatPromptTemplate` · `MessagesPlaceholder` · `prompt \| llm`) |
| 벡터 검색 | FAISS (`faiss-cpu`, 로컬 파일 인덱스) · MMR 검색 |
| 문서 분할 | `langchain-text-splitters` (Markdown 인지 `RecursiveCharacterTextSplitter`) |
| LLM | OpenAI `ChatOpenAI` (기본 `gpt-5-nano`) 또는 Anthropic `ChatAnthropic` (선택) |
| 임베딩 | OpenAI `text-embedding-3-small` 또는 로컬 HuggingFace `BAAI/bge-m3` (선택) |
| 크롤링 | `requests` · `BeautifulSoup4` · `lxml` (robots.txt 준수, 캐시) |
| 세션 저장 | JSON 파일 (원자적 쓰기) |
| 설정 | `python-dotenv` |

## 프로젝트 구조

```
├── app.py            # Streamlit 웹앱 (ChatGPT 스타일 UI, 세션 사이드바)
├── rag.py            # RAG 파이프라인 (질문 재작성 → 검색 → 답변 스트리밍)
├── ingest.py         # 크롤링 → 청크 → 임베딩 → FAISS 저장
├── crawler.py        # 허용 도메인 한정 크롤러, HTML → 텍스트 변환
├── storage.py        # 채팅 세션 저장/불러오기/삭제
├── config.py         # 경로, 허용 규칙, 환경변수
├── tests/test_core.py
├── MYPLAN.md         # 제작 계획·과정 요약
├── requirements.txt
├── .env.example
└── .streamlit/config.toml   # 다크 테마
```

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| "문서 인덱스가 아직 없습니다" | `python ingest.py` 를 먼저 실행했는지 |
| "`.env` 에 …_API_KEY 를 설정하세요" | `.env` 파일 위치(프로젝트 루트)와 키 값 |
| "인덱스는 …임베딩으로 만들어졌지만…" | 인덱스를 만들 때와 같은 `EMBEDDING_PROVIDER` 로 맞추거나 `--reindex-only` |
| `python ingest.py` 에서 수집 페이지가 0개 | 네트워크 연결, 사내 프록시, 시작 URL 확인 |
| 답변이 "찾지 못했다"로 자주 나옴 | `--max-pages`/`--max-depth` 를 늘리거나 관련 제품 문서를 `--seed` 로 추가 |
| 화면이 ChatGPT와 다르게 보임 | 사용자 CSS는 Streamlit 1.40 이상 기준입니다. `pip install -U streamlit` |

## 알아둘 점

- 답변은 인덱싱된 문서 범위 안에서만 만들어집니다. 문서가 갱신되면 `python ingest.py --refresh` 로 다시 수집하세요.
- 두 사이트의 이용 약관과 robots.txt를 존중하세요. 수집한 문서 내용은 로컬 학습·사내 사용 목적으로만 쓰는 것을 권장합니다.
- 질문과 검색된 문서 조각은 선택한 LLM/임베딩 서비스(OpenAI 또는 Anthropic)로 전송됩니다. 외부로 보내고 싶지 않다면 임베딩은 `huggingface` 로컬 모델을 사용하세요. (답변 모델은 외부 API를 사용합니다.)
# mykubedocs
