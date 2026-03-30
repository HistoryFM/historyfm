# HistoryFM — Frontend Implementation Overview

## Architecture

- **Framework**: Next.js 16 (App Router) with static generation
- **Styling**: Tailwind CSS 4 with custom CSS variables for theming
- **Content**: Markdown files parsed at build time via `remark`/`remark-html`
- **State**: Client-side only — localStorage for preferences, bookmarks, and poll votes
- **No backend**: Everything is static. This document identifies integration points for a future API.

## Directory Structure

```
frontend/
├── content/                     # Build-time content (gitignored, populated by sync script)
│   ├── novels/
│   │   ├── louisiana-purchase/
│   │   │   ├── meta.json        # { title, slug, chapterCount, description }
│   │   │   ├── chapter-01.md
│   │   │   └── ...
│   │   ├── the-dark-horse/
│   │   └── nullification-crisis/
│   └── polls.json               # Poll questions and options
├── scripts/
│   └── sync-content.sh          # Copies chapters from novel repos into content/
├── src/
│   ├── app/
│   │   ├── layout.tsx           # Root layout: header, footer, ThemeProvider wrapper
│   │   ├── page.tsx             # Home page: hero, novel grid, featured poll
│   │   ├── ThemeProvider.tsx    # Client context: dark mode + font size (localStorage)
│   │   ├── ThemeToggle.tsx      # Light/dark/system toggle button
│   │   ├── FontSizeControl.tsx  # A−/A+ font size buttons
│   │   ├── NovelCard.tsx        # Novel card with bookmark resume link
│   │   ├── novels/
│   │   │   ├── [slug]/
│   │   │   │   ├── page.tsx             # Novel detail: chapter list
│   │   │   │   ├── ChapterList.tsx      # Client component: chapter list with bookmark highlight
│   │   │   │   ├── ContinueReadingBanner.tsx  # Resume banner if bookmark exists
│   │   │   │   └── [chapter]/
│   │   │   │       ├── page.tsx         # Chapter reader: rendered markdown
│   │   │   │       ├── ReadingProgress.tsx    # Scroll-based progress bar
│   │   │   │       └── BookmarkSaver.tsx      # Auto-saves reading position
│   │   └── polls/
│   │       ├── page.tsx         # All polls page
│   │       └── PollCard.tsx     # Interactive poll with localStorage voting
│   └── lib/
│       ├── content.ts           # Build-time content loading: getAllNovels, getChapter, etc.
│       └── useBookmark.ts       # Client hook: reading bookmark persistence
└── globals.css                  # CSS variables, theme tokens, prose-chapter styles
```

## Content Pipeline

1. Novel source files live outside the frontend at `<novel-folder>/drafts/v3_polish/chapter_XX.md`
2. `scripts/sync-content.sh` copies them into `frontend/content/novels/<slug>/chapter-XX.md` and generates a `meta.json` per novel
3. At build time, `src/lib/content.ts` reads these files using Node.js `fs` to produce static pages

### Data Shapes

**Novel meta.json:**
```json
{ "title": "The Louisiana Purchase", "slug": "louisiana-purchase", "chapterCount": 12, "description": "..." }
```

**Chapter markdown format:**
```markdown
# Chapter N: Title

## Section Heading

Prose body text...
```
No YAML frontmatter. Title extracted from the `# ` heading.

**polls.json:**
```json
{
  "polls": [
    {
      "id": "next-era",
      "question": "Which historical era should we dramatize next?",
      "options": [
        { "id": "revolution", "label": "The American Revolution", "description": "1775–1783" }
      ]
    }
  ]
}
```

## Pages & Routes

| Route | File | Generation | Description |
|-------|------|-----------|-------------|
| `/` | `app/page.tsx` | Static | Hero, novel grid, featured poll |
| `/novels/[slug]` | `app/novels/[slug]/page.tsx` | SSG (`generateStaticParams`) | Novel detail with chapter list |
| `/novels/[slug]/[chapter]` | `app/novels/[slug]/[chapter]/page.tsx` | SSG (`generateStaticParams`) | Full chapter reader |
| `/polls` | `app/polls/page.tsx` | Static | All polls |

## Client-Side Features (localStorage)

All client state uses localStorage. Keys:

| Feature | Storage Key | Value |
|---------|------------|-------|
| Dark mode | `theme` | `"light"` / `"dark"` / `"system"` |
| Font size | `font-size` | `"small"` / `"default"` / `"large"` |
| Reading bookmark | `reading-progress-{novelSlug}` | `BookmarkData` JSON (chapterSlug, chapterNumber, chapterTitle, scrollPercent, timestamp) |
| Poll vote | `poll-vote-{pollId}` | Selected option ID string |
| Poll tallies | `poll-votes-{pollId}` | `Record<string, number>` JSON |

## Theming

CSS variables defined in `globals.css` under `:root` (light) and `.dark` (dark mode):
- Colors: `--theme-parchment`, `--theme-ink`, `--theme-accent`, `--theme-rule`, etc.
- Font scale: `--theme-font-scale` (0.9 / 1 / 1.15)
- Tailwind theme tokens map to these via `@theme inline` block

A FOUC-prevention `<script>` in `layout.tsx` applies theme class and font scale before React hydrates.

## Key Functions (src/lib/content.ts)

| Function | Returns | Used By |
|----------|---------|---------|
| `getAllNovels()` | `NovelMeta[]` | Home page |
| `getNovelMeta(slug)` | `NovelMeta` | Novel detail page |
| `getChapterList(novelSlug)` | `ChapterInfo[]` | Novel detail page |
| `getChapter(novelSlug, chapterSlug)` | `ChapterContent` (includes HTML, word count, reading time) | Chapter reader |

## Integration Points for Backend

When adding a backend API, these are the natural replacement points:

1. **Polls** → Replace localStorage voting in `PollCard.tsx` with API calls (`POST /api/polls/{id}/vote`, `GET /api/polls/{id}/results`). The `polls.json` file becomes seed data or moves to a database.

2. **Reading bookmarks** → Replace `useBookmark.ts` localStorage with API calls (`PUT /api/bookmarks/{novelSlug}`, `GET /api/bookmarks`). Enables cross-device sync when users are authenticated.

3. **Authentication** → Add an auth provider wrapping the app in `layout.tsx`. Gate bookmark sync and poll voting behind auth. The static reading experience stays public.

4. **Content management** → Replace `scripts/sync-content.sh` + filesystem reads with a CMS or API. The `content.ts` functions become API clients instead of `fs.readFileSync` calls.

5. **Analytics** → Add reading progress tracking (which chapters are most read, drop-off points). The `BookmarkSaver` component already tracks scroll percentage.

## Build & Run

```bash
# Sync content from novel repos
cd frontend && bash scripts/sync-content.sh

# Development
npm run dev          # http://localhost:3000

# Production build
npm run build        # Static generation of all pages
npm run start        # Serve production build
```
