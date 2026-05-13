# Web Search Skill

Use this skill when the user asks you to search the web, look up current information, find news, research a topic, retrieve live data, or answer questions about recent events.

## Available Search Methods

The `fetch_url` tool only performs **GET** requests. Three search methods are available, each with different coverage and reliability.

---

## Method 1: DuckDuckGo Web Search (primary)

Query DuckDuckGo's HTML search endpoint. **Works from most residential/office networks.** May be blocked from datacenter/VPS IPs.

### URL format

```
https://html.duckduckgo.com/html/?q={URL_ENCODED_QUERY}
```

Replace `{URL_ENCODED_QUERY}` with the search terms URL-encoded (e.g., `python+programming` for "python programming").

### Headers

Always set a realistic browser User-Agent:

```
headers={
  "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.9"
}
```

### Parsing the HTML

DDG returns results as `<div class="result ...">` elements with this structure:

```html
<div class="result results_links results_links_deep web-result" id="r1-0">
  <div class="result__body">
    <div class="result__title">
      <a class="result__a" href="https://actual-url.com">Result Title</a>
    </div>
    <a class="result__snippet" href="https://actual-url.com">
      Snippet/description text of the search result...
    </a>
    <div class="result__url">displayed-url.com</div>
  </div>
</div>
```

**Extraction instructions:**
1. Find all `<div class="result ...">` blocks (they contain `web-result` in the class)
2. For each block:
   - **Title**: extract the text of `<a class="result__a">` inside `.result__title`
   - **URL**: extract the `href` attribute of `<a class="result__a">`
   - **Snippet**: extract the text of `<a class="result__snippet">`
3. Format results as a numbered markdown list with `[Title](URL)` and snippet below

### Limit

Show the **top 5-10 results** to the user. Ask if they want to dig deeper into any result.

---

## Method 2: DuckDuckGo Instant Answer API (fallback)

For **factual/definitional queries** — uses DDG's structured API. **Works from almost all IPs** but returns fewer results (infobox-style).

### URL format

```
https://api.duckduckgo.com/?q={URL_ENCODED_QUERY}&format=json&no_html=1&skip_disambig=1
```

### Response format

Returns JSON. Key fields:
- `Abstract` — summary text (may be empty)
- `AbstractSource` — source of the abstract
- `AbstractURL` — URL of the source
- `Heading` — topic heading
- `Image` — image URL (if available)
- `Results` — list of additional results (each with `Text`, `FirstURL`)
- `RelatedTopics` — related topic links (may be nested with `Name` and `Topics` sub-array)
- `Infobox` — structured data (if available)
- `Answer` / `AnswerType` — direct answer (e.g. for calculator, conversion queries)
- `Definition` / `DefinitionSource` — dictionary-style definitions

### Presentation

- If `Abstract` is non-empty, show it as a summary block with source attribution
- If `Results` has entries, list them as links
- If `RelatedTopics` has entries, show them as "Related" links
- If `Answer` is present, show as a highlighted direct answer
- If results are insufficient, fall back to Method 1 or Method 3

---

## Method 3: Wikipedia Search API (fallback)

For **encyclopedic queries** — Wikipedia's API is always available and returns clean JSON.

### URL format

```
https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={URL_ENCODED_QUERY}&format=json&srlimit=10
```

### Response format

Returns JSON under `query.search` — each result has:
- `title` — page title
- `snippet` — excerpt with `<span class="searchmatch">` highlights
- `pageid` — numeric page ID
- `wordcount` — article length indicator

To get the full page summary, use:
```
https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=1&explaintext=1&titles={PAGE_TITLE}&format=json
```

### Presentation

Show titles as links to `https://en.wikipedia.org/wiki/{TITLE}` with snippet excerpts.

---

## How to Choose a Method

1. **For general web search** (news, products, blog posts, docs): **Method 1 (DDG HTML)**
2. **For factual questions** (what is X, capital of Y, definition of Z): **Method 2 (DDG Instant Answer)**
3. **For encyclopedic research** (history, science, biography): **Method 3 (Wikipedia)**
4. **If Method 1 returns a CAPTCHA page** (detect `<form id="challenge-form">` or `anomaly-modal` in the response): fall back to **Method 2** or **Method 3**

---

## Example Flow

**User:** "What's the latest version of Python?"

**Step 1 — Try DDG HTML search:**
```
fetch_url(url="https://html.duckduckgo.com/html/?q=latest+python+version+2026",
  headers={"User-Agent": "Mozilla/5.0 ..."})
```

**Step 2a — If results found:** parse `<div class="result">` blocks, extract titles/URLs/snippets, present to user.

**Step 2b — If CAPTCHA detected:** fall back to DDG Instant Answer API:
```
fetch_url(url="https://api.duckduckgo.com/?q=latest+python+version&format=json&no_html=1&skip_disambig=1")
```
Parse JSON `Abstract`, `Results`, `RelatedTopics` and present to user.

**Step 3 — Follow up:** Ask if the user wants to open any specific result to read more.

---

## Important Notes

- The `fetch_url` tool returns raw HTML/JSON — you must parse it yourself using string matching or regex.
- DuckDuckGo may change their HTML structure; adapt your parsing if results look wrong.
- Respect rate limits — avoid hammering the search endpoints.
- If all methods fail, inform the user honestly and suggest alternative approaches.
