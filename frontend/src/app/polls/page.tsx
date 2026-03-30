import fs from "fs";
import path from "path";
import PollCard from "./PollCard";

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

function getPolls(): Poll[] {
  const filePath = path.join(process.cwd(), "content/polls.json");
  const data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
  return data.polls;
}

export default function PollsPage() {
  const polls = getPolls();

  return (
    <div className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="font-display text-3xl sm:text-4xl tracking-tight text-ink mb-4">
        Reader Polls
      </h1>
      <p className="text-base text-ink-light mb-10 leading-relaxed">
        Help us decide what to write next. Cast your vote below.
      </p>
      <hr className="border-t border-rule mb-10" />

      <div className="space-y-8">
        {polls.map((poll) => (
          <PollCard key={poll.id} poll={poll} />
        ))}
      </div>
    </div>
  );
}
