import Link from "next/link";
import {
  getAllNovels,
  getNovelMeta,
  getChapterList,
  getChapter,
} from "@/lib/content";
import ReadingProgress from "./ReadingProgress";
import BookmarkSaver from "./BookmarkSaver";
import FontSizeControl from "@/app/FontSizeControl";

export function generateStaticParams() {
  const novels = getAllNovels();
  const params: { slug: string; chapter: string }[] = [];
  for (const novel of novels) {
    const chapters = getChapterList(novel.slug);
    for (const ch of chapters) {
      params.push({ slug: novel.slug, chapter: ch.slug });
    }
  }
  return params;
}

export default async function ChapterPage({
  params,
}: {
  params: Promise<{ slug: string; chapter: string }>;
}) {
  const { slug, chapter: chapterSlug } = await params;
  const novel = getNovelMeta(slug);
  const chapters = getChapterList(slug);
  const chapter = await getChapter(slug, chapterSlug);

  const currentIndex = chapters.findIndex((c) => c.slug === chapterSlug);
  const prev = currentIndex > 0 ? chapters[currentIndex - 1] : null;
  const next =
    currentIndex < chapters.length - 1 ? chapters[currentIndex + 1] : null;

  return (
    <>
      <ReadingProgress />
      <BookmarkSaver
        novelSlug={slug}
        chapterSlug={chapterSlug}
        chapterNumber={chapter.number}
        chapterTitle={chapter.title}
      />

      <article className="mx-auto max-w-[65ch] px-6 py-12 sm:py-16">
        {/* Breadcrumb */}
        <div className="mb-8 flex items-center gap-2 text-xs uppercase tracking-widest text-ink-muted">
          <Link href={`/novels/${slug}`} className="hover:text-ink transition-colors">
            {novel.title}
          </Link>
          <span aria-hidden="true">/</span>
          <span>Chapter {chapter.number}</span>
        </div>

        {/* Title */}
        <header className="mb-10">
          <h1 className="font-display text-2xl sm:text-3xl tracking-tight text-ink leading-snug">
            {chapter.title}
          </h1>
          <div className="mt-3 flex items-center justify-between">
            <p className="text-xs uppercase tracking-widest text-ink-muted">
              {chapter.readingTimeMinutes} min read
            </p>
            <FontSizeControl />
          </div>
          <hr className="mt-6 border-t border-rule" />
        </header>

        {/* Prose */}
        <div
          className="prose-chapter"
          dangerouslySetInnerHTML={{ __html: chapter.htmlContent }}
        />

        {/* Prev / Next */}
        <nav className="mt-16 border-t border-rule pt-8 flex justify-between gap-4">
          {prev ? (
            <Link
              href={`/novels/${slug}/${prev.slug}`}
              className="group text-sm text-ink-muted hover:text-ink transition-colors"
            >
              <span className="text-xs uppercase tracking-widest block mb-1">
                Previous
              </span>
              <span className="text-ink group-hover:text-accent-dark transition-colors">
                {prev.title}
              </span>
            </Link>
          ) : (
            <div />
          )}
          {next ? (
            <Link
              href={`/novels/${slug}/${next.slug}`}
              className="group text-sm text-ink-muted hover:text-ink transition-colors text-right"
            >
              <span className="text-xs uppercase tracking-widest block mb-1">
                Next
              </span>
              <span className="text-ink group-hover:text-accent-dark transition-colors">
                {next.title}
              </span>
            </Link>
          ) : (
            <Link
              href={`/novels/${slug}`}
              className="text-sm text-ink-muted hover:text-ink transition-colors text-right"
            >
              <span className="text-xs uppercase tracking-widest block mb-1">
                Finished
              </span>
              <span>Back to {novel.title}</span>
            </Link>
          )}
        </nav>
      </article>
    </>
  );
}
