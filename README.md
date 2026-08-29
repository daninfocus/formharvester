![formharvester](docs/logo.jpeg)

[![PyPI](https://img.shields.io/pypi/v/formharvester.svg?logo=pypi&logoColor=white&color=3775A9)](https://pypi.org/project/formharvester/)
[![Latest release (Windows)](https://custom-icon-badges.demolab.com/github/v/release/dariomory/formharvester?label=Windows%20exe&logo=windows11&logoColor=white&color=0078D6)](https://github.com/dariomory/formharvester/releases/latest/download/formharvester.exe)

**Website:** [formharvester.com](https://formharvester.com) · **Documentation:** [formharvester.com/docs](https://formharvester.com/docs/)

FormHarvester is an AI-assisted form intelligence engine.
It navigates the open web autonomously - executing searches, parsing page structure, extracting contact signals, and interacting with forms at the browser level. Built on async browser with stealth fingerprinting, proxy rotation, and a pluggable captcha solver interface.

## What it does

FormHarvester combines discovery, passive site analysis, contact-signal
extraction, and optional form interaction in one browser-driven workflow:

1. Search for target businesses with Google queries.
2. Normalize and deduplicate the discovered site URLs.
3. Visit contact pages and landing pages through Selenium Chrome.
4. Extract public email addresses and their source URLs.
5. Detect browser-visible technologies with confidence and evidence.
6. Optionally fill and submit a contact form using the configured profile.

Form submissions are opt-in through `engine.send_form` or
`HarvesterOptions(send_form=True)`. Use `send_form=False` for discovery,
testing, and technology-only scans.

## Contents

- [Installation and quick start](#how-to-run)
- [Configuration](#configuration)
- [Technology detection and inference](#technology-detection-and-inference)
- [Library API](#programmatic-use-library-api)
- [CLI output files](#cli-output-files)
- [Development and testing](#development-and-testing)

![The FormHarvester desktop app](docs/screenshot-gui.png)

## How to run

#### Desktop app
[Download formharvester.exe](https://github.com/dariomory/formharvester/releases/latest/download/formharvester.exe)
(built automatically on every release by `.github/workflows/release-windows-exe.yml`), then run it.
Everything is configured in the app: no files to edit.

#### Python
```bash
pip install "formharvester[gui]"
formharvester gui      # desktop app
formharvester run      # headless harvest loop
```

The `[gui]` extra pulls in pywebview. Plain `pip install formharvester` gives
you the CLI and the library without it.

## Configuration

Settings live in `formharvester.json`, and each campaign (form-fill details plus
the search queries) lives in `profiles/<name>.json`. Run
`formharvester settings path` to see where they are stored. The location is the
working directory when a config already exists there, otherwise
`~/.formharvester`; `FORMHARVESTER_HOME` overrides both.

Scraped emails, progress files and error logs are written to `data/` and
`log/` inside that same directory.

### From the GUI

`formharvester gui` opens four tabs: **Run** picks the active campaign and
streams the live console, **Campaigns** edits and manages campaign details and
query lists, **Leads** shows locally persisted enrichment and submission
history, and **Settings** covers the engine, search pacing, captcha solver,
and LLM provider configuration. The Campaigns tab controls whether a campaign
uses direct text or LLM-generated form content and configures selective
autopilot safety rules.

The top-right header shows live **LLM** and **CAPTCHA** health indicators. Green
means the configured provider accepted the credentials and returned a valid
response; yellow means the provider is missing, unreachable, or rejected the
credentials; gray means that integration is disabled. Checks run in the
background, are cached briefly, and do not generate LLM content or submit a
CAPTCHA.

Campaign **Search queries** are sent to Google. Optional **URL filters** are
matched against the URLs returned by Google; they do not search page content or
specifically identify contact pages. Leave them empty to keep all Google result
links, subject to normal deduplication and the visited-site filter.

### From the CLI

```bash
formharvester settings show                     # print current settings
formharvester settings set engine.headless true # values are validated
formharvester settings set google.max_pages 5

formharvester profile list
formharvester profile create solar
formharvester profile use solar

formharvester run --profile solar --headless --max-pages 5

formharvester discover "roofing companies austin" > targets.txt
```

Flags on `run` override the saved settings for that run only.

### Settings reference

| Key | Meaning |
| --- | --- |
| `engine.send_form` | Submit the contact form once filled. Disable to save time. |
| `engine.headless` | Run the browser hidden. |
| `engine.skip_ads` | Skip ad results. |
| `engine.max_time` | Seconds allowed per website. |
| `engine.generate_email_sources` | Also record the URL each email came from. |
| `engine.debug_form` | Fill forms but never submit them. |
| `engine.detect_technologies` | Passively detect technologies exposed by each site. |
| `google.start_page` | Results page to start from. |
| `google.max_pages` | Result pages to walk per query. |
| `google.min_delay` / `google.max_delay` | Random delay range, in seconds, between searches. |
| `google.captcha_sleep` | Minutes to pause after a search captcha. 0 disables. |
| `google.search_timer` | Minutes between search batches. |
| `captcha.provider` | `deathbycaptcha`, `2captcha`, `none`, or blank to auto-detect from the credentials you filled in. |
| `captcha.twocaptcha_api_key` | 2captcha API key. |
| `captcha.dbc_username` / `captcha.dbc_password` | DeathByCaptcha credentials. |
| `llm.enabled` | Generate Subject and Message from the selected campaign's saved prompt fields. Disabled by default. |
| `llm.provider` | `openai`, `anthropic`, or `deepseek`. |
| `llm.model` | Provider model name; editable because model catalogs change. |
| `llm.*_api_key` | API key for the selected provider. Keys stay in local settings and are never logged or exported. |
| `llm.review_before_submit` | In the desktop GUI, pause with editable generated content and require approval before submitting. |
| `llm.request_timeout` | Maximum seconds for a provider request. |

### LLM form content

In the GUI, enable **Use LLM-generated content** beside the Subject and Message
fields in the Campaigns tab. When it is off, those fields contain the exact text
that will be submitted. When it is on, they become separate **Subject prompt**
and **Message prompt** fields; the direct submission text is preserved, so
switching modes is reversible without copying text. Provider, model, review,
and API-key settings remain in the Settings tab.

The LLM returns the final Subject and Message as structured JSON; the other
form fields continue using the existing deterministic profile values. If the
toggle is on without a key for the selected provider, the GUI warns you and
directs you to Settings before a run can start.

Generation and submission are separate safety gates. `engine.send_form=false`
remains read-only and avoids the LLM call. With submission enabled, disabling
**Review generated content before submitting** submits successful output
automatically. Enabling review pauses the desktop app with editable Subject and
Message fields and requires **Approve and submit**; **Skip** never clicks the
site's submit button. If a provider request or response fails, the site is
marked `LLM_ERROR` and is never submitted.

The prompt includes only structured context: the target URL, detected
technologies, public emails, configured identity fields, and visible form
field metadata. It does not send raw HTML, cookies, scripts, or page source.
Provider usage can incur charges, and configured campaign identity details are
sent to the selected provider when generation is enabled.

### Qualification and selective autopilot

Campaigns can optionally enable **Selective autopilot**. FormHarvester scores
each site deterministically using observable signals such as contact-form
availability, public emails, and technology fingerprints. The Leads tab shows
the score and the reasons behind it. Autopilot submits only when the campaign
score threshold, technology rules, contact-form requirement, domain cooldown,
daily limit, and per-run limit all pass. Autopilot is disabled by default and
requires LLM-generated content; manual review is enabled by default for this
mode.

Use **Dry run** to discover, enrich, score, and generate drafts while making
submission impossible. Suppressed domains remain blocked until explicitly
restored. Every submission attempt, policy result, draft, and suppression
change is written to the local lead database.

## Programmatic use (library API)

Since `2.4.0` FormHarvester ships a library API so you can drive the engine from
your own code - no settings files or progress files required. The CLI is
unchanged.

```python
from formharvester import FormHarvester, FormFillDetails, HarvesterOptions

details = FormFillDetails(
    first_name="Jane", last_name="Doe",
    email="jane@example.com", phone="1234567890",
    subject="Enquiry", message="Hi, I'd like a quote.",
)

with FormHarvester(details, HarvesterOptions(send_form=True, headless=True)) as fh:
    result = fh.harvest("https://acme.com")
    print(result.status, result.submitted, result.emails)

    urls = fh.discover("roofing companies austin")   # search -> site URLs
    for r in fh.harvest_many(urls):
        print(r.url, r.status)
```

`result.status` is one of `SUBMITTED`, `FORM_NOT_FOUND`, `BUTTON_NOT_FOUND`,
`VISITED`, `LLM_ERROR`, `REVIEW_SKIPPED`, `POLICY_BLOCKED`, `NOT_QUALIFIED`,
`DRY_RUN`, or `ERROR` - the same tokens the CLI
writes to its progress file. When generation succeeds, `result.generated`
contains the generated Subject and Message plus provider/model metadata.
One-shot helpers `harvest_site(url, details)` and `harvest_sites(urls, details)`
are also available.

`discover()` raises `CaptchaError` rather than blocking; set
`HarvesterOptions.captcha_sleep` to wait it out instead.

For library use, inject a provider client or configure one explicitly:

```python
from formharvester import FormFillDetails, FormHarvester, HarvesterOptions

details = FormFillDetails(
    email="jane@example.com",
    subject="Ask about a website rebuild",
    message="Write a concise introduction using our frontend experience.",
)

options = HarvesterOptions(
    send_form=True,
    llm_enabled=True,
    llm_provider="openai",
    llm_model="gpt-5",
    llm_api_key="YOUR_API_KEY",
)

with FormHarvester(details, options) as fh:
    result = fh.harvest("https://example.com")
    print(result.status, result.generated)
```

Manual review is a desktop-GUI workflow. A library caller that enables
`llm_review_before_submit` with submission enabled receives a configuration
error instead of an interactive prompt; use an injected client for automated
library workflows.

## Technology detection and inference

The full guide is published at
[`formharvester.com/docs`](https://formharvester.com/docs/). The detector is
local, passive, and enabled by default; it adds no paid API and does not load a
browser extension.

### How the scan works

When Selenium has loaded a target page, FormHarvester collects browser-visible
signals from the same session already being used for harvesting:

- HTML, generator tags, DOM markers, and known framework globals.
- Script, stylesheet, iframe, and performance-resource URLs.
- Cookies by name only; cookie values are never written to evidence.
- Response headers when Chrome exposes them through performance logging.

The detector matches those signals against local rules and returns a technology
name, category, optional version, confidence score, and human-readable evidence.
The landing page and contact page are merged into one site result.

### Inference policy

Client-side technologies and infrastructure often leave strong fingerprints.
Backend frameworks usually do not. A site may be built with Django or FastAPI
but expose only generic HTML through a reverse proxy, so FormHarvester does not
claim a backend from a URL shape or a vague response. Backend results are
reported only when a meaningful signal exists and are marked as lower-confidence
inferences where appropriate.

### Library usage

```python
from formharvester import FormFillDetails, FormHarvester, HarvesterOptions

with FormHarvester(
    FormFillDetails(),
    HarvesterOptions(send_form=False, detect_technologies=True),
) as fh:
    result = fh.harvest("https://example.com")

for technology in result.technologies:
    print(technology.name, technology.category, technology.confidence)
    for evidence in technology.evidence:
        print("  ", evidence.detail)
```

Set `detect_technologies=False` to disable detection. The existing harvest
status and email behavior is unchanged when detection is disabled or when a
page exposes no reliable technology signals.

### Result shape

`HarvestResult.technologies` is a list of `TechnologyMatch` objects:

```json
{
  "name": "Next.js",
  "category": "Web framework",
  "version": null,
  "confidence": 0.98,
  "evidence": [
    {
      "source": "dom_or_url",
      "value": "__NEXT_DATA__ or /_next/",
      "detail": "Next.js runtime marker"
    }
  ]
}
```

Confidence is a practical signal-strength score, not a statistical
probability. Scores near `1.0` represent distinctive direct fingerprints;
lower scores represent weaker or inferred signals.

### CLI and GUI behavior

CLI runs append one JSON object per scanned site to
`data/<profile>_technologies.jsonl`. The record contains the target URL, UTC
scan time, and the same structured technology matches returned by the library.
The desktop GUI exposes a **Detect site technologies** setting and prints a
short summary in the Run console.

Lead intelligence is available from the CLI as JSON lines, metrics, or CSV:

```bash
formharvester leads list
formharvester leads metrics
formharvester leads export --output leads.csv
```

Operational lead state is stored in `data/leads.sqlite3`; campaign-specific
CSV exports are written beside it. The database keeps scores, evidence,
generated drafts, policy decisions, suppression changes, and submission audit
events locally.

### Live smoke-test example

On a read-only smoke scan of `https://mory.dev`, the detector returned:

| Technology | Category | Confidence | Interpretation |
| --- | --- | ---: | --- |
| Astro | Web framework | 0.98 | Direct Astro runtime marker. |
| Vercel | Hosting | 0.95 | Vercel hostname or response-header marker. |
| Django | Backend framework | 0.60 | Lower-confidence HTML inference, not proof. |

Technology stacks change over time, so this table is an example of the result
format rather than a permanent claim about the site.

### External detectors and extensions

FormHarvester does not require Wappalyzer, a hosted API, or a browser extension.
This keeps the desktop package self-contained and avoids per-lookup API costs.
An external provider can be added later behind an optional provider interface if
broader coverage is needed.

## Package layout (2.4.2)

```
src/formharvester/
├── __init__.py          # public API (FormHarvester, FormFillDetails, …)
├── api.py               # library API
├── engine/              # Selenium browser engine + Chrome driver
├── scraper/             # web search + email scraping
├── form_handler/        # contact-page discovery, field fill, submit
├── captcha/             # solver providers (DeathByCaptcha, 2captcha) + detection
├── llm/                 # provider-neutral form-content generation
├── settings.py          # JSON settings, profiles and file locations
├── cli/                 # typer commands (`formharvester`)
├── gui/                 # pywebview desktop app (web/ holds its HTML, CSS, JS)
└── utils/               # root-domain, email regex, link filters
```

## Building the Windows executable (maintainers)

`.github/workflows/release-windows-exe.yml` builds `formharvester.exe` with PyInstaller and
attaches it to the GitHub Release for any pushed `v*` tag (also runnable manually via
workflow_dispatch). To build it locally:

```bash
uv sync --no-group dev --extra gui
uv pip install pyinstaller
uv run pyinstaller packaging/formharvester.spec
```

The executable launches the desktop app. The `formharvester` command installed
by pip is the CLI.

___

This project is released under the [MIT License](LICENSE). You are free to use, modify, and distribute this software, provided that the original copyright notice and license terms are included in all copies or substantial portions of the software.
