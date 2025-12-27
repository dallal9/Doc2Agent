# Architecture

> **Goal**: Personal local document Q&A agent — Chainlit UI → Multi-agent system → Ollama LLM, with PDF ingestion, SQLite storage, and semantic page querying.

---

## High-level Design

```mermaid
flowchart TB
    subgraph UI [User Interface]
        CL[Chainlit Web UI]
    end

    subgraph Ingestion [PDF Ingestion Pipeline]
        PDF[PDF File] --> Parser[PDFParser<br/>PyMuPDF]
        Parser --> RawPages[Raw Pages<br/>text/tables/images]
        RawPages --> IngAgent[Ingestion Agent<br/>LLM]
        IngAgent --> EnrichedPages[Enriched Pages<br/>names/dates/headings]
    end

    subgraph Storage [Persistence Layer]
        EnrichedPages --> SQLite[(SQLite DB<br/>Unified Cache + FTS5)]
        EnrichedPages -.->|Optional Export| JSON[(JSON File)]
    end

    subgraph Agents [Multi-Agent System]
        Main[Main Agent]
        Reviewer[Reviewer Agent]
        Validator[Validator Agent]
        Main -->|review_draft| Reviewer
        Main -->|validate_against_personal_info| Validator
    end

    subgraph LLM [LLM Backend]
        Ollama[Ollama<br/>Local Inference]
    end

    CL -->|upload PDF| Ingestion
    CL -->|chat message| Main
    Main -->|query_pages / search_fts| Storage
    Main -->|generate| Ollama
    Reviewer -->|generate| Ollama
    Validator -->|generate| Ollama
    IngAgent -->|generate| Ollama
    Main -->|response| CL
```

---

## Full System Diagram

```mermaid
flowchart LR
    subgraph User
        Browser[Browser]
    end

    subgraph ChainlitApp [app/chainlit_app.py]
        OnStart[on_chat_start]
        OnMessage[on_message]
        ChatSteps[chat_with_steps]
    end

    subgraph ChatAssistant [src/chat/assistant.py]
        IngestPDF[ingest_pdf]
        PrepareTurn[prepare_turn]
        FinalizeTurn[finalize_turn]
    end

    subgraph PDFPipeline [src/tools/pdf_parser.py]
        PDFParser[PDFParser]
        ExtractMeta[extract_metadata]
        ParsePages[parse_pages]
    end

    subgraph IngestionAgent [src/agents/ingestion.py]
        CreateIng[create_ingestion_agent]
        IngestPage[ingest_page]
    end

    subgraph MainAgent [src/agents/main.py]
        CreateMain[create_main_agent]
        MainDeps[MainDeps]
    end

    subgraph Tools [src/agents/tooling.py]
        ReaderTools[register_reader_tools]
        DBTools[register_database_tools]
        ExtractionTools[register_extraction_tools]
    end

    subgraph StorageLayer [src/storage/sqlite_store.py]
        SQLiteStore[SQLiteStore]
        InsertDoc[insert_document]
        QueryPages[query_pages]
        SearchFTS[search_text]
    end

    subgraph Schemas [src/schemas/document.py]
        PageSchema[PageSchema]
        DocSchema[DocumentSchema]
        DocMeta[DocumentMetadata]
    end

    Browser --> OnMessage
    OnMessage --> IngestPDF
    OnMessage --> ChatSteps
    IngestPDF --> PDFParser
    PDFParser --> ExtractMeta
    PDFParser --> ParsePages
    ParsePages --> IngestPage
    IngestPage --> PageSchema
    IngestPDF --> InsertDoc
    ChatSteps --> PrepareTurn
    PrepareTurn --> MainDeps
    ChatSteps --> CreateMain
    CreateMain --> ReaderTools
    CreateMain --> DBTools
    DBTools --> QueryPages
    DBTools --> SearchFTS
    QueryPages --> PageSchema
```

---

## Components

| Layer | Component | Responsibility |
|-------|-----------|----------------|
| **UI** | Chainlit | Chat interface, file uploads, session state |
| **Chat** | ChatAssistant | Orchestrates ingestion and chat turns |
| **Agents** | Main Agent | Answers questions using tools |
| | Reviewer Agent | Reviews draft answers for quality |
| | Validator Agent | Validates claims against personal info |
| | Ingestion Agent | Enriches pages with semantic metadata |
| **Tools** | PDFParser | PyMuPDF-based PDF extraction |
| | Database Tools | query_pages, get_all_pages, search_fts |
| | Reader Tools | search_document, get_section |
| **Storage** | SQLiteStore | Documents/pages persistence with FTS5 |
| **Schemas** | PageSchema | Page-level metadata and content |
| | DocumentSchema | Full document with metadata + pages |

---

## Directory Layout

```
Doc2Agent/
├── app/
│   └── chainlit_app.py          # Chainlit UI entry point
├── src/
│   ├── agents/
│   │   ├── base.py              # create_agent, run_agent
│   │   ├── main.py              # Main agent + MainDeps
│   │   ├── reviewer.py          # Reviewer agent
│   │   ├── ingestion.py         # Ingestion agent for page enrichment
│   │   └── tooling.py           # Tool registration
│   ├── agents_config/
│   │   ├── agents.json          # Agent configs (model, backend)
│   │   ├── prompts.json         # System prompts
│   │   └── schemas.py           # Config schemas
│   ├── chat/
│   │   └── assistant.py         # ChatAssistant orchestrator
│   ├── schemas/
│   │   └── document.py          # PageSchema, DocumentSchema
│   ├── storage/
│   │   └── sqlite_store.py      # SQLite persistence + FTS
│   ├── tools/
│   │   ├── pdf.py               # Legacy pypdf tools
│   │   ├── pdf_parser.py        # PDFParser (PyMuPDF)
│   │   └── retrieval.py         # Search utilities
│   ├── bootstrap.py             # App initialization
│   └── logging.py               # Logging setup
├── tests/
├── docs/
│   ├── architecture.md          # This file
│   └── local_design.md          # Refactoring design doc
├── pyproject.toml
├── env.example
└── README.md
```

---

## Data Flow

### PDF Ingestion (Cache-First)

```mermaid
sequenceDiagram
    participant U as User
    participant CL as Chainlit
    participant CA as ChatAssistant
    participant DB as SQLiteStore
    participant PP as PDFParser
    participant IA as IngestionAgent

    U->>CL: Upload PDF
    CL->>CA: ingest_pdf(path)
    CA->>DB: get_document_by_path(path)
    alt Cache hit (same mod_time)
        DB-->>CA: DocumentMetadata
        CA->>DB: load_document(doc_id)
        DB-->>CA: DocumentSchema (cached)
        CA-->>CL: "Loaded cached: file.pdf"
    else Cache miss
        CA->>PP: parse_document()
        PP-->>CA: DocumentSchema (raw)
        loop For each page
            CA->>IA: ingest_page(page_data)
            IA-->>CA: PageSchema (enriched)
            CA-->>CL: Progress update
        end
        CA->>DB: insert_document()
        CA-->>CL: "Ingested N pages"
    end
    CL-->>U: Status message
```

### Document Selection

```mermaid
sequenceDiagram
    participant U as User
    participant CL as Chainlit
    participant CA as ChatAssistant
    participant DB as SQLiteStore

    U->>CL: /docs or chat start
    CL->>CA: list_cached_documents()
    CA->>DB: list_documents()
    DB-->>CA: List of DocumentMetadata
    CA-->>CL: Cached docs list
    CL-->>U: Show action buttons
    U->>CL: Click "Select doc"
    CL->>CA: load_cached_document(doc_id)
    CA->>DB: load_document(doc_id)
    DB-->>CA: DocumentSchema
    CA-->>CL: "Loaded file.pdf"
    CL-->>U: PDF preview + status
```

### Chat Query

```mermaid
sequenceDiagram
    participant U as User
    participant CL as Chainlit
    participant CA as ChatAssistant
    participant MA as MainAgent
    participant DB as SQLiteStore
    participant RA as ReviewerAgent

    U->>CL: Ask question
    CL->>CA: prepare_turn(message)
    CA-->>CL: prompt, deps
    CL->>MA: run_agent(prompt, deps)
    MA->>DB: query_pages(filters)
    DB-->>MA: Matching pages
    MA->>RA: review_draft(question, draft)
    RA-->>MA: Feedback or final answer
    MA-->>CL: Response
    CL->>CA: finalize_turn(reply)
    CL-->>U: Display answer
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint |
| `INLINE_DOC_MAX_CHARS` | `20000` | Max chars to inline in prompt |
| `PDF_SQLITE_DIR` | `data` | Directory for SQLite database files |
| `PDF_JSON_DIR` | `data` | Directory for optional JSON export |
| `PDF_JSON_MAX_BYTES` | `2000000` | Max file size for JSON export |
| `USE_ENRICHMENT` | `true` | Enable LLM page enrichment |
| `SHOW_INGESTION_LOGS` | `false` | Show per-page progress in UI |
| `SHOW_REASONING` | `true` | Show `<think>` tags in UI |
| `PERSONAL_INFO_JSON` | - | JSON with user's personal data |

### Agent Configs

Defined in `src/agents_config/agents.json`:

```json
{
  "main": { "model": "ministral-3:3b", "temperature": 0.2 },
  "reviewer": { "model": "deepseek-r1:8b", "temperature": 0.1 },
  "validator": { "model": "ministral-3:3b", "temperature": 0.1 },
  "ingestion": { "model": "ministral-3:3b", "temperature": 0.0 }
}
```

---

## Tech Stack

- **UI**: Chainlit
- **Agents**: pydantic-ai
- **LLM**: Ollama (local inference)
- **PDF**: PyMuPDF (fitz)
- **Storage**: SQLite + FTS5
- **Config**: python-dotenv

---

## Running

```bash
# Install dependencies
uv sync

# Configure
cp env.example .env

# Start Ollama
ollama serve

# Run Chainlit
uv run chainlit run app/chainlit_app.py
```
