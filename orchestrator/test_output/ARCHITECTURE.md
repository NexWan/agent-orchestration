# XPath Visualizer — Architecture

## Overview

A Flask web application that allows users to input XML documents and XPath expressions, then visually highlights the matched nodes in the rendered XML tree.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────┐
│                 Browser (Client)            │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ XML Input│  │XPath Input│  │ Result   │  │
│  │ Textarea │  │  Field   │  │ Panel    │  │
│  └────┬─────┘  └────┬─────┘  └────▲─────┘  │
│       └─────────────┘             │         │
│              AJAX POST ───────────┘         │
└─────────────────────────────────────────────┘
                    │ HTTP
                    ▼
┌─────────────────────────────────────────────┐
│               Flask Server                  │
│                                             │
│  ┌──────────────┐    ┌─────────────────┐   │
│  │  Routes /    │───▶│  XPath Service  │   │
│  │  API Layer   │    │  (lxml)         │   │
│  └──────────────┘    └────────┬────────┘   │
│                               │             │
│                    ┌──────────▼──────────┐  │
│                    │  XML Renderer       │  │
│                    │  (annotate matches) │  │
│                    └─────────────────────┘  │
└─────────────────────────────────────────────┘
```

---

## Components

### 1. Flask Application (`app.py`)
- Entry point; registers routes and configures the app.

### 2. Routes / API Layer (`routes.py`)
| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Serve main HTML page |
| `/evaluate` | POST | Accept `{xml, xpath}` JSON, return annotated result |

### 3. XPath Service (`services/xpath_service.py`)
- Parse XML with `lxml.etree`.
- Evaluate the XPath expression.
- Return matched node references and any errors.

### 4. XML Renderer (`services/xml_renderer.py`)
- Walk the parsed XML tree.
- Wrap matched nodes in a sentinel marker.
- Serialize back to an HTML-safe, pretty-printed string.

### 5. Frontend (`static/` + `templates/`)
| File | Role |
|------|------|
| `templates/index.html` | Main page layout |
| `static/css/style.css` | Syntax coloring, highlight styles |
| `static/js/main.js` | AJAX call, render annotated XML, error display |

---

## Data Flow

1. User pastes XML + XPath in the browser.
2. `main.js` POSTs `{xml, xpath}` to `/evaluate`.
3. Flask route calls **XPath Service** → parses XML, runs expression.
4. Matched node objects passed to **XML Renderer** → produces HTML string with `<span class="match">` wrappers around hits.
5. Response JSON `{html, match_count, error}` returned to browser.
6. `main.js` injects the HTML into the result panel; CSS highlights matches.

---

## Key Design Decisions

- **`lxml`** for robust XPath 1.0 support and fast C-level parsing.
- **Stateless API** — no session or database; all state lives in the request.
- **HTML annotation on the server** — keeps the client simple; only needs to inject a string.
- **JSON error envelope** — frontend always receives `{html, match_count, error}` so it can display parse/evaluation errors gracefully.

---

## Project Structure

```
xpath-visualizer/
├── app.py                    # Flask app factory + entry point
├── routes.py                 # URL routes
├── services/
│   ├── __init__.py
│   ├── xpath_service.py      # XML parsing & XPath evaluation
│   └── xml_renderer.py       # Annotated HTML serialization
├── templates/
│   └── index.html            # Single-page UI
├── static/
│   ├── css/
│   │   └── style.css         # Styles + highlight colors
│   └── js/
│       └── main.js           # AJAX + DOM updates
└── requirements.txt          # flask, lxml
```
