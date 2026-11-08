# MYPLAN.md — 애플리케이션 제작 계획 및 과정 요약

> 최종 프로젝트: **Kubernetes / Red Hat 공식문서 기반 RAG 챗봇 (LangChain + Streamlit)**
> 이 문서는 코드를 작성하기 전에 요구사항을 정리하고, 어떤 순서와 근거로 구현했는지를 요약한 것입니다.

---

## 1. 요구사항 정리

| 구분 | 요구사항 | 해석 / 결정 |
|---|---|---|
| 지식 범위 | `kubernetes.io/docs` 및 `docs.redhat.com/en` 공식문서(문서 내 관련 링크 포함)**만** 사용 | 두 사이트에서 시작해 문서 안의 링크를 따라가되, **허용된 호스트·경로 안의 링크만** 수집 (그 밖의 사이트는 수집하지 않음) |
| 답변 방식 | RAG 파이프라인으로 채팅 | 검색된 문서 조각만 근거로 답변하고, 근거가 없으면 "찾지 못했다"고 답하도록 프롬프트 제한 |
| 프레임워크 | LangChain 기반 | `langchain-core` 의 LCEL 구성요소(Prompt, Message, Runnable) 중심으로 구현 |
| 대화 기억 | 과거 대화를 **세션 형식**으로 기억 | 채팅 세션 단위로 저장(JSON), 사이드바에서 과거 세션 다시 열기·삭제 |
| 화면 | ChatGPT와 비슷한 화면 | 사이드바(새 채팅 + 채팅 기록) + 가운데 대화 영역 + 하단 입력창, 다크 테마 |
| 웹 서비스 | 로컬에서 Streamlit | `streamlit run app.py` |
| 벡터 DB | 외부 서버 불필요 | **FAISS(로컬 파일 인덱스)** 사용 — 서버 설치 없이 폴더에 저장 |
| 산출물 | MYPLAN.md → 앱 완성 → README.md | 이 문서 → 코드 → README.md 순서로 작성 |
| 참고 소스 | `2일차.ipynb` | 노트북의 RAG 구성(OpenAI `text-embedding-3-small` + FAISS + LCEL + `gpt-5-nano`, `.env` 로 키 관리, conda `py310`)을 기본값으로 반영 — 8번 항목 참고 |

---

## 2. 설계 결정과 이유

1. **크롤러 직접 구현 (requests + BeautifulSoup)**
   - 허용 도메인/경로 규칙을 코드로 강제해 "공식문서만 사용" 조건을 보장.
   - robots.txt 확인, 요청 간 지연, 캐시(재실행 시 재다운로드 방지)로 사이트에 부담을 주지 않음.
2. **FAISS 로컬 인덱스**
   - 외부 Vector DB 서버가 필요 없고, `data/faiss_index/` 폴더 하나로 끝남.
3. **질문 재작성(Query Rewrite) 단계**
   - 문서는 영어, 질문은 한국어일 수 있고, "그럼 그건 어떻게 해?" 같은 후속 질문도 있음.
   - 대화 기록을 반영해 **독립적인 영어 검색어**로 바꿔서 검색 정확도를 높임.
4. **MMR 검색**
   - 비슷한 조각만 반복해서 가져오는 것을 줄이고, 다양한 문서에서 근거를 확보.
5. **출처 번호 인용**
   - 같은 URL의 조각은 하나의 번호로 묶어 `[1]`, `[2]` 로 인용하고, 답변 아래에 링크 목록 표시.
6. **세션 저장은 JSON 파일**
   - DB 없이 `data/sessions/*.json` 으로 저장 → 앱을 껐다 켜도 기록 유지.
7. **LLM/임베딩 교체 가능**
   - `.env` 의 `LLM_PROVIDER`, `EMBEDDING_PROVIDER` 로 OpenAI / Anthropic / 로컬 HuggingFace 선택.

---

## 3. 파이프라인 개요

```
[오프라인: 인덱스 생성]  python ingest.py
  시작 URL ─▶ 크롤링(허용 규칙, robots, 캐시) ─▶ HTML→텍스트 ─▶ 청크 분할
          ─▶ 임베딩 ─▶ FAISS 인덱스(data/faiss_index/) 저장

[온라인: 채팅]  streamlit run app.py
  질문 ─▶ (대화기록 반영) 검색어 재작성 ─▶ FAISS MMR 검색 ─▶ 컨텍스트 구성
       ─▶ LLM 답변 스트리밍(출처 인용) ─▶ 세션 JSON 저장
```

---

## 4. 파일 구조

```
k8s-redhat-rag-chatbot/
├── MYPLAN.md            # (이 문서) 제작 계획/과정 요약
├── README.md            # 소개, 사용 방법, 기술 스택
├── app.py               # Streamlit 웹앱 (ChatGPT 스타일 UI)
├── rag.py               # RAG 파이프라인 (재작성 → 검색 → 답변)
├── ingest.py            # 크롤링 → 청크 → 임베딩 → FAISS 저장
├── crawler.py           # 허용 도메인 한정 크롤러 / HTML 텍스트 추출
├── storage.py           # 채팅 세션 저장/불러오기/삭제
├── config.py            # 경로, 허용 규칙, 환경변수 설정
├── requirements.txt
├── .env.example
├── .gitignore
├── .streamlit/config.toml   # 다크 테마
└── tests/test_core.py   # 크롤러 규칙·텍스트 추출·세션 저장 단위 테스트
```

---

## 5. 작업 순서 (체크리스트)

- [x] 1. 요구사항 분석 및 설계 결정 (이 문서)
- [x] 2. `config.py` — 경로, 허용 규칙(호스트·경로), 환경변수
- [x] 3. `crawler.py` — URL 정규화/허용 판정, robots.txt, BFS 크롤, HTML→텍스트
- [x] 4. `ingest.py` — 청크 분할(Markdown 인지), 배치 임베딩, FAISS 저장, 인덱스 메타 기록
- [x] 5. `storage.py` — 세션 JSON 저장/목록/삭제 (경로 조작 방지, 원자적 쓰기)
- [x] 6. `rag.py` — LLM/임베딩 팩토리, 질문 재작성, MMR 검색, 컨텍스트·출처 구성, 스트리밍 답변
- [x] 7. `app.py` — ChatGPT 스타일 UI, 세션 사이드바, 스트리밍 출력, 출처 표시, 설정 안내
- [x] 8. 단위 테스트 작성·실행 (네트워크/LLM 없이 검증 가능한 부분)
- [x] 9. `README.md` 작성
- [x] 10. 문법 검사 및 최종 점검

---

## 6. 검증 계획과 한계

- **자동 검증 가능한 부분**: URL 허용 규칙, 링크 정규화, HTML→텍스트 변환, 세션 저장/삭제/경로 안전성 → `tests/test_core.py`
- **실행 결과**: `python -m unittest discover -s tests` → 13개 중 12개 통과, 1개(rag 헬퍼 테스트)는 `langchain-core` 미설치로 건너뜀. 모든 `.py` 파일 `py_compile` 문법 검사 통과.
- **직접 확인이 필요한 부분**: 실제 크롤링(네트워크), 임베딩/LLM 호출(API 키), Streamlit 화면 모양
  - 제작 환경에는 외부 네트워크와 LangChain/Streamlit 패키지가 없어 **종단 간(end-to-end) 실행은 하지 못했음**.
  - 실행 순서: `pip install -r requirements.txt` → `.env` 작성 → `python ingest.py` → `streamlit run app.py`

## 7. 위험 요소와 대응

| 위험 | 대응 |
|---|---|
| 사이트 구조(HTML) 변경으로 본문 추출 실패 | 본문 후보 선택자를 여러 개 두고 `main` 으로 폴백, 너무 짧은 페이지는 제외 |
| Red Hat 문서가 방대해 전체 수집이 오래 걸림 | 호스트당 최대 페이지 수·깊이 제한(`.env`/CLI), 시작 URL 추가 지원 |
| 영어 문서 vs 한국어 질문 | 질문을 영어 검색어로 재작성 + 다국어 임베딩 사용 |
| 문서에 없는 질문에 지어낸 답변 | 컨텍스트 밖 추측 금지 프롬프트, 근거 없으면 "찾지 못함" 안내 |
| 문서 내용에 섞인 지시문(프롬프트 주입) | 컨텍스트를 "참고 자료(데이터)"로만 취급하도록 시스템 프롬프트에 명시 |

---

## 8. 참고 소스(2일차.ipynb) 반영 내용

| 노트북의 구성 | 이 프로젝트에 반영한 방법 |
|---|---|
| `OpenAIEmbeddings(model="text-embedding-3-small")` | 임베딩 기본값으로 동일하게 사용 (`EMBEDDING_PROVIDER=openai`) |
| `FAISS.from_documents(...)` 로컬 벡터DB | 동일하게 FAISS 사용, 인덱스를 파일로 저장해 앱에서 재사용 |
| `RecursiveCharacterTextSplitter` (500/100, 일반 텍스트 300~1000자 권장) | 같은 분할기 계열 사용. 기술 문서라 Markdown 구조를 인식하는 분할기, 1000/150 으로 설정 (`.env` 로 조정) |
| `retriever` + `ChatPromptTemplate` + `ChatOpenAI(model="gpt-5-nano")` LCEL 체인 | 같은 `prompt \| llm` 구조. 스트리밍·출처 표시를 위해 검색 단계를 분리 |
| "문서에 없으면 답변하지 마라" 프롬프트 | 문서 밖 추측 금지, 근거 없으면 "찾지 못함" 안내로 유지 |
| `MessagesPlaceholder("history")` 대화 기억 문제 | 세션별 대화를 JSON 으로 저장하고 최근 N 왕복을 `history` 로 전달 |
| `.env` + `load_dotenv()` | 동일 (`.env.example` 제공) |
| `streamlit run app.py`, conda `py310` | 동일한 실행 방법, README 에 conda 사용법 추가 |
| `gpt-5-nano` 모델 | 기본 모델로 사용. 추론 모델은 `temperature` 를 바꿀 수 없어 해당 모델에서는 값을 지정하지 않도록 처리 |

참고: 노트북 안의 강사 메모에는 "Streamlit 말고 빠른 웹프레임워크"라는 문구가 있지만, 이번 과제 요구사항이 **로컬 Streamlit** 이므로 Streamlit 을 유지했습니다.

---

## 9. 구현 중 조정한 점

| 항목 | 조정 내용 | 이유 |
|---|---|---|
| 버튼 너비 | `use_container_width` 대신 CSS로 전체 너비 처리 | 최신 Streamlit에서 이 인자가 바뀌거나 제거될 수 있어 버전 영향을 줄임 |
| 첫 화면 | 질문이 들어오면 안내 화면(예시 질문)을 숨기고 바로 대화 표시 | 응답이 스트리밍되는 동안 첫 화면이 남아 있는 문제 방지 |
| 사이드바 | 화면 마지막에 그림 | 방금 저장된 대화가 기록 목록에 바로 나타나도록 |
| 봇 캐시 | 인덱스 파일 수정시각을 캐시 키로 사용 | `ingest.py` 로 인덱스를 다시 만들어도 앱 재시작 없이 반영 |
| 크롤링 중단 | `Ctrl+C` 시 지금까지 수집한 페이지로 인덱싱 진행 | 오래 걸리는 수집을 중간에 끊어도 결과를 버리지 않기 위해 |
| 리다이렉트 | 최종 URL이 허용 범위를 벗어나면 폐기 | "공식문서만 사용" 조건을 리다이렉트로도 우회하지 못하게 |
