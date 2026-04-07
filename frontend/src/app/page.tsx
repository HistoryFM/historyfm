import fs from "fs";
import path from "path";
import Link from "next/link";
import { getAllNovels } from "@/lib/content";
import NovelCard from "./NovelCard";
import PollCard from "./polls/PollCard";

interface PollOption {
  id: string;
  label: string;
  description: string;
}

interface Poll {
  id: string;
  question: string;
  options: PollOption[];
}

function getFeaturedPoll(): Poll | null {
  const filePath = path.join(process.cwd(), "content/polls.json");
  const data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
  return data.polls?.[0] ?? null;
}

export default function HomePage() {
  const novels = getAllNovels();
  const featuredPoll = getFeaturedPoll();

  return (
    <div className="mx-auto max-w-4xl px-6 py-16">
      {/* Hero */}
      <section className="text-center mb-16">
        <h1 className="font-display text-4xl sm:text-5xl tracking-tight text-ink mb-4">
          HistoryFM
        </h1>
        <p className="text-lg text-ink-light max-w-xl mx-auto leading-relaxed">
          The past, dramatized. Historical fiction that turns real events
          into gripping, character-driven stories.
        </p>
        <hr className="mx-auto mt-8 w-24 border-t border-rule" />
      </section>

      {/* Novel grid */}
      <section>
        <h2 className="text-xs uppercase tracking-widest text-ink-muted mb-8 text-center">
          Available Novels
        </h2>
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
          {novels.map((novel) => (
            <NovelCard
              key={novel.slug}
              slug={novel.slug}
              title={novel.title}
              description={novel.description}
              chapterCount={novel.chapterCount}
            />
          ))}
        </div>
      </section>

      {/* Featured poll */}
      {featuredPoll && (
        <section className="mt-20">
          <hr className="border-t border-rule mb-12" />
          <h2 className="text-xs uppercase tracking-widest text-ink-muted mb-8 text-center">
            Have Your Say
          </h2>
          <div className="max-w-2xl mx-auto">
            <PollCard poll={featuredPoll} />
            <p className="mt-6 text-center">
              <Link
                href="/polls"
                className="text-sm text-accent hover:text-accent-dark transition-colors"
              >
                View all polls &rarr;
              </Link>
            </p>
          </div>
        </section>
      )}
    </div>
  );
}
