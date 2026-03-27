# Personal Finance Manager — Project Specification

## Overview

A personal finance management web app for a single user. The user's bank does not provide an API, so all transaction data is imported via Excel file uploads (.xlsx/.xls/.csv). The app must handle duplicate detection, automatic categorization, configurable rules, rich reporting, subscription tracking, anomaly detection, and full transaction management.

## Tech Stack

| Layer        | Technology                                    |
|-------------|-----------------------------------------------|
| Backend     | Python 3.12+, FastAPI                         |
| Templating  | Jinja2 (server-side rendered HTML)            |
| Database    | PostgreSQL 16                                 |
| ORM         | SQLAlchemy 2.x (async) + Alembic migrations  |
| Charts      | Chart.js (rendered client-side)               |
| CSS         | Tailwind CSS (via CDN) or a lightweight CSS framework like Pico CSS — keep it simple, no build step |
| Deployment  | Docker Compose (app + PostgreSQL containers)  |
| Excel Parse | openpyxl + pandas                             |

**No authentication required** — this is a single-user personal app. No login, no user management.

## Architecture

```
project-root/
├── docker-compose.yml
├── Dockerfile
├── alembic/                    # DB migrations
│   ├── alembic.ini
│   └── versions/
├── app/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Settings (DB URL, etc.)
│   ├── database.py             # SQLAlchemy engine + session
│   ├── models/                 # SQLAlchemy models
│   │   ├── transaction.py
│   │   ├── category.py
│   │   ├── categorization_rule.py
│   │   ├── subscription.py
│   │   └── import_log.py
│   ├── routers/                # FastAPI route handlers
│   │   ├── dashboard.py
│   │   ├── transactions.py
│   │   ├── upload.py
│   │   ├── categories.py
│   │   ├── rules.py
│   │   ├── reports.py
│   │   ├── subscriptions.py
│   │   └── api.py              # JSON endpoints for chart data
│   ├── services/               # Business logic
│   │   ├── import_service.py   # Excel parsing + dedup
│   │   ├── categorization.py   # Auto-categorization engine
│   │   ├── subscription_detector.py
│   │   ├── anomaly_detector.py
│   │   └── reporting.py
│   ├── templates/              # Jinja2 HTML templates
│   │   ├── base.html           # Layout with nav, theme toggle
│   │   ├── dashboard.html
│   │   ├── transactions.html
│   │   ├── upload.html
│   │   ├── categories.html
│   │   ├── rules.html
│   │   ├── reports.html
│   │   ├── subscriptions.html
│   │   └── partials/           # Reusable fragments (table rows, modals, etc.)
│   └── static/
│       ├── css/
│       ├── js/
│       └── img/
├── tests/
├── requirements.txt
└── CLAUDE.md
```

## Database Schema

### transactions
```
id              SERIAL PRIMARY KEY
date            DATE NOT NULL
value_date      DATE                    -- optional, some banks have a separate value date
description     TEXT NOT NULL            -- raw description from bank
description_clean TEXT                   -- cleaned/normalized description
amount          DECIMAL(12,2) NOT NULL   -- negative = expense, positive = income
currency        VARCHAR(3) NOT NULL DEFAULT 'CHF'
category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL
is_manually_categorized BOOLEAN DEFAULT FALSE
notes           TEXT                     -- user-added notes
merchant        VARCHAR(255)             -- extracted/editable merchant name
import_hash     VARCHAR(64) UNIQUE NOT NULL  -- for duplicate detection
import_log_id   INTEGER REFERENCES import_logs(id)
created_at      TIMESTAMP DEFAULT NOW()
updated_at      TIMESTAMP DEFAULT NOW()
```

### categories
```
id              SERIAL PRIMARY KEY
name            VARCHAR(100) NOT NULL UNIQUE
icon            VARCHAR(50)              -- emoji or icon class
color           VARCHAR(7)               -- hex color for charts
parent_id       INTEGER REFERENCES categories(id) ON DELETE SET NULL  -- subcategories
is_income       BOOLEAN DEFAULT FALSE
sort_order      INTEGER DEFAULT 0
```

### categorization_rules
```
id              SERIAL PRIMARY KEY
pattern         VARCHAR(255) NOT NULL    -- substring or regex pattern
match_type      VARCHAR(20) NOT NULL     -- 'contains', 'starts_with', 'regex', 'exact'
category_id     INTEGER REFERENCES categories(id) ON DELETE CASCADE
priority        INTEGER DEFAULT 0        -- higher = checked first
is_active       BOOLEAN DEFAULT TRUE
created_at      TIMESTAMP DEFAULT NOW()
```

### subscriptions
```
id              SERIAL PRIMARY KEY
name            VARCHAR(255) NOT NULL
merchant        VARCHAR(255)
expected_amount DECIMAL(12,2)
currency        VARCHAR(3) DEFAULT 'CHF'
frequency       VARCHAR(20) NOT NULL     -- 'monthly', 'quarterly', 'yearly', 'weekly'
category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL
is_active       BOOLEAN DEFAULT TRUE
last_seen       DATE
next_expected   DATE
notes           TEXT
```

### import_logs
```
id              SERIAL PRIMARY KEY
filename        VARCHAR(255) NOT NULL
imported_at     TIMESTAMP DEFAULT NOW()
total_rows      INTEGER
new_rows        INTEGER
duplicate_rows  INTEGER
error_rows      INTEGER
status          VARCHAR(20)              -- 'success', 'partial', 'failed'
notes           TEXT
```

## Core Features — Detailed Requirements

### 1. Excel Upload & Import

**File support:** .xlsx, .xls, .csv

**Column mapping UI:**
- On first upload, show a preview of the first 10 rows
- Let user map columns: date, description, amount (or debit/credit), currency, balance
- Save column mapping per detected file format/structure so future uploads auto-map
- Support both single amount column (+/-) and separate debit/credit columns

**Duplicate detection:**
- Generate `import_hash` from: `SHA256(date + description + amount + currency)`
- On import, skip any row whose hash already exists in the DB
- Show import summary: X new, Y duplicates skipped, Z errors

**Import log:**
- Record every import attempt with stats
- Allow viewing past imports and which transactions came from each

**Data cleaning on import:**
- Trim whitespace from descriptions
- Normalize date formats
- Generate `description_clean` by removing excessive spaces, card numbers, reference codes
- Try to extract merchant name from description

### 2. Automatic Categorization

**Rule-based engine:**
- Match transaction descriptions against `categorization_rules` table
- Rules checked in priority order (highest first)
- Match types: `contains` (case-insensitive), `starts_with`, `exact`, `regex`
- Only auto-categorize if `is_manually_categorized` is FALSE

**Default seed rules (pre-populated):**
```
"migros|coop|aldi|lidl|denner|spar"     → Food & Groceries
"sbb|zvv|uber|taxi|parking|benzin|fuel"  → Transport
"netflix|spotify|disney|apple.com|google storage" → Subscriptions / Recurring
"rent|miete|wohnung"                      → Rent / Housing
"swisscom|sunrise|salt|elektr|strom"      → Utilities / Bills
"doctor|arzt|apotheke|pharmacy|css|swica" → Health / Insurance
"zalando|amazon|digitec|galaxus"          → Shopping
"hotel|airbnb|booking|flight|flug"        → Travel
"kino|cinema|restaurant|bar|cafe"         → Entertainment
"salary|lohn|gehalt"                       → Income / Salary
```

**Rule management UI:**
- CRUD for rules: add pattern, pick match type, assign category, set priority
- Test a rule: show which existing transactions would match
- Bulk re-categorize: apply rules retroactively to all uncategorized transactions
- "Create rule from transaction" — click a transaction, auto-suggest a rule from its description

### 3. Transaction Management

**Transaction list view:**
- Sortable, paginated table (50 per page)
- Columns: Date, Description, Merchant, Amount, Currency, Category, Notes
- Color-code by category
- Inline quick-edit for category and notes (click to edit)

**Filtering & Search:**
- Free-text search across description, merchant, notes
- Filter by: date range, category, amount range, currency, uncategorized only, income/expense
- Combine multiple filters
- Save filter presets (stored in DB or localStorage)

**Transaction detail / edit:**
- Edit: description_clean, merchant, category, notes
- Mark `is_manually_categorized = TRUE` when user changes category
- Split transaction into multiple categories (stretch goal)

### 4. Categories

**Default categories (pre-seeded):**
- Food & Groceries
- Rent / Housing
- Transport
- Subscriptions / Recurring
- Entertainment
- Health / Insurance
- Shopping
- Travel
- Utilities / Bills
- Income / Salary
- Uncategorized (system default, cannot delete)

**Category management:**
- Add, edit, delete categories
- Each has: name, icon (emoji), color (hex picker), parent category (optional)
- Deleting a category moves its transactions to "Uncategorized"
- Merge two categories

### 5. Reports & Visualizations

All charts rendered with **Chart.js** on the client side. Data served via JSON API endpoints.

**5.1 Dashboard (home page):**
- Current month summary: total income, total expenses, net
- Spending by category (doughnut chart)
- Daily spending trend (bar chart for current month)
- Recent transactions (last 10)
- Active subscriptions count + next upcoming payment
- Alerts: anomalies detected, uncategorized transaction count

**5.2 Monthly Spending Breakdown:**
- Bar chart: spending per category, month selectable
- Pie/doughnut chart: category proportions
- Table: category totals with % of total spend
- Compare to previous month (delta shown)

**5.3 Category Trends Over Time:**
- Line chart: selected categories over N months
- Multi-select categories to compare
- Configurable time range (3m, 6m, 1y, all)

**5.4 Income vs Expenses:**
- Stacked/grouped bar chart by month
- Net savings line overlay
- Savings rate % per month

**5.5 Top Merchants / Payees:**
- Ranked bar chart: top 20 merchants by total spend
- Filter by date range
- Click merchant → see all transactions for that merchant

**5.6 Net Worth / Balance Over Time:**
- Line chart: cumulative balance over time
- Calculated from running sum of all transactions
- Multi-currency: show per-currency or converted to base currency

**5.7 Year-over-Year Comparison:**
- Grouped bar chart: monthly totals across years
- Category-level YoY comparison
- Table with % change

### 6. Subscription Tracker

**Auto-detection logic:**
- Scan transactions for recurring patterns: same merchant + similar amount + regular interval
- Detection heuristic: ≥3 occurrences with consistent interval (±3 days tolerance for monthly, ±7 for quarterly)
- Suggest detected subscriptions for user confirmation

**Subscription management:**
- List all subscriptions: name, amount, frequency, category, last seen, next expected
- Mark as active/inactive
- Manual add/edit
- Alert if a subscription is overdue (expected but not seen)
- Monthly/yearly subscription cost total

### 7. Anomaly Detection

**Detection methods:**
- **Unusual amount:** Transaction amount > 2 standard deviations from mean for that merchant/category
- **New merchant:** First time seeing this merchant
- **Frequency anomaly:** Unexpected transaction from a subscription merchant outside normal schedule
- **Large transaction:** Above configurable threshold (default: 500 CHF)

**UI:**
- Anomaly badge on dashboard
- Dedicated anomaly list with explanation for each flag
- Dismiss/acknowledge anomalies

### 8. UI / UX Requirements

**Theme:**
- Light and dark mode with toggle button (persist preference in localStorage)
- Clean, minimal design — think banking app aesthetics
- Use CSS variables for theming

**Navigation:**
- Sidebar or top nav with: Dashboard, Transactions, Upload, Reports, Subscriptions, Categories, Rules
- Active page highlighted
- Mobile-responsive (sidebar collapses to hamburger menu)

**Interactions:**
- Use HTMX or vanilla JS for interactive parts (inline editing, filter updates without full page reload)
- Toast notifications for actions (import complete, rule saved, etc.)
- Confirmation modals for destructive actions (delete category, etc.)

**Tables:**
- Striped rows, hover highlight
- Sticky header
- Responsive: horizontal scroll on mobile

## Docker Compose Setup

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://finapp:finapp@db:5432/finapp
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - uploads:/app/uploads

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: finapp
      POSTGRES_PASSWORD: finapp
      POSTGRES_DB: finapp
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U finapp"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
  uploads:
```

## Development Guidelines

- Use async SQLAlchemy throughout (asyncpg driver)
- Type hints on all function signatures
- Pydantic models for any API request/response schemas
- Use Alembic for all schema changes — never raw SQL for DDL
- Business logic lives in `services/`, routes are thin and delegate
- Templates extend `base.html`; use Jinja2 template inheritance and `{% block %}` consistently
- Keep JavaScript minimal and vanilla — use HTMX for dynamic updates where possible
- All monetary amounts stored as DECIMAL(12,2), never float
- Dates stored as DATE, timestamps as TIMESTAMP WITH TIME ZONE
- All queries should be timezone-aware (default: Europe/Zurich)

## Implementation Order

Build in this sequence, each phase should be fully working before moving on:

1. **Project skeleton:** Docker Compose, FastAPI app, DB connection, Alembic setup, base template with nav + theme toggle
2. **Models & migrations:** All SQLAlchemy models, initial Alembic migration, seed default categories
3. **Upload & import:** Excel parsing, column mapping, duplicate detection, import log
4. **Transaction list:** Paginated table, sorting, basic filtering, search
5. **Categorization engine:** Rule matching, default rules seeded, auto-categorize on import
6. **Category & rule management:** CRUD UIs for categories and rules, bulk re-categorize
7. **Dashboard:** Summary cards, spending doughnut, daily trend, recent transactions
8. **Reports:** All chart pages (monthly breakdown, trends, income vs expenses, top merchants, balance over time, YoY)
9. **Subscription tracker:** Detection logic, management UI, alerts
10. **Anomaly detection:** Detection logic, dashboard badges, anomaly list
11. **Polish:** Mobile responsiveness, toast notifications, error handling, loading states

## Non-Goals (Out of Scope)

- Multi-user / authentication
- Bank API integrations
- Mobile native app
- Real-time sync
- Budget planning / goal setting (could be added later)
- Receipt scanning / OCR
