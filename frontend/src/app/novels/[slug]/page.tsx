import Link from "next/link";
import { getAllNovels, getNovelMeta, getChapterList } from "@/lib/content";
import ContinueReadingBanner from "./ContinueReadingBanner";
import ChapterList from "./ChapterList";

export function generateStaticParams() {
  return getAllNovels().map((n) => ({ slug: n.slug }));
}

export default async function NovelPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const novel = getNovelMeta(slug);
  const chapters = getChapterList(slug);

  return (
    <div className="mx-auto max-w-3xl px-6 py-16">
      <Link
        href="/"
        className="text-xs uppercase tracking-widest text-ink-muted hover:text-ink transition-colors"
      >
        &larr; All Novels
      </Link>

      <h1 className="font-display text-3xl sm:text-4xl tracking-tight text-ink mt-6 mb-4">
        {novel.title}
      </h1>
      <p className="text-base leading-relaxed text-ink-light max-w-xl mb-8">
        {novel.description}
      </p>

      <hr className="border-t border-rule mb-8" />

      <ContinueReadingBanner novelSlug={slug} />

      <h2 className="text-xs uppercase tracking-widest text-ink-muted mb-6">
        Chapters
      </h2>

      <ChapterList
        novelSlug={slug}
        chapters={chapters.map((ch) => ({ slug: ch.slug, title: ch.title }))}
      />
    </div>
  );
}
