import fs from "fs";
import path from "path";
import { remark } from "remark";
import html from "remark-html";

const contentDir = path.join(process.cwd(), "content/novels");

export interface NovelMeta {
  title: string;
  slug: string;
  chapterCount: number;
  description: string;
}

export interface ChapterInfo {
  slug: string;
  number: string;
  title: string;
}

export interface ChapterContent extends ChapterInfo {
  htmlContent: string;
  wordCount: number;
  readingTimeMinutes: number;
}

export function getAllNovels(): NovelMeta[] {
  const slugs = fs.readdirSync(contentDir).filter((f) => {
    return fs.statSync(path.join(contentDir, f)).isDirectory();
  });

  return slugs.map((slug) => {
    const metaPath = path.join(contentDir, slug, "meta.json");
    const meta = JSON.parse(fs.readFileSync(metaPath, "utf-8"));
    return meta as NovelMeta;
  });
}

export function getNovelMeta(slug: string): NovelMeta {
  const metaPath = path.join(contentDir, slug, "meta.json");
  return JSON.parse(fs.readFileSync(metaPath, "utf-8"));
}

export function getChapterList(novelSlug: string): ChapterInfo[] {
  const novelDir = path.join(contentDir, novelSlug);
  const files = fs
    .readdirSync(novelDir)
    .filter((f) => f.startsWith("chapter-") && f.endsWith(".md"))
    .sort();

  return files.map((file) => {
    const number = file.replace("chapter-", "").replace(".md", "");
    const raw = fs.readFileSync(path.join(novelDir, file), "utf-8");
    const title = extractTitle(raw);
    return { slug: `chapter-${number}`, number, title };
  });
}

export async function getChapter(
  novelSlug: string,
  chapterSlug: string
): Promise<ChapterContent> {
  const filePath = path.join(contentDir, novelSlug, `${chapterSlug}.md`);
  const raw = fs.readFileSync(filePath, "utf-8");

  const title = extractTitle(raw);
  const number = chapterSlug.replace("chapter-", "");

  // Remove the H1 title line before rendering (we render it separately)
  const bodyMd = raw.replace(/^#\s+.+\n+/, "");

  const result = await remark().use(html).process(bodyMd);
  const htmlContent = result.toString();

  const wordCount = raw.split(/\s+/).length;
  const readingTimeMinutes = Math.ceil(wordCount / 250);

  return { slug: chapterSlug, number, title, htmlContent, wordCount, readingTimeMinutes };
}

function extractTitle(markdown: string): string {
  const match = markdown.match(/^#\s+(.+)$/m);
  return match ? match[1].trim() : "Untitled";
}
