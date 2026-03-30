"use client";

import { useState, useEffect } from "react";

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

export default function PollCard({ poll }: { poll: Poll }) {
  const storageKey = `poll-vote-${poll.id}`;
  const votesKey = `poll-votes-${poll.id}`;

  const [voted, setVoted] = useState<string | null>(null);
  const [votes, setVotes] = useState<Record<string, number>>({});

  useEffect(() => {
    const savedVote = localStorage.getItem(storageKey);
    if (savedVote) setVoted(savedVote);

    const savedVotes = localStorage.getItem(votesKey);
    if (savedVotes) {
      setVotes(JSON.parse(savedVotes));
    } else {
      // Initialize with 0 votes
      const initial: Record<string, number> = {};
      for (const opt of poll.options) initial[opt.id] = 0;
      setVotes(initial);
    }
  }, [poll.options, storageKey, votesKey]);

  function handleVote(optionId: string) {
    if (voted) return;
    const newVotes = { ...votes, [optionId]: (votes[optionId] || 0) + 1 };
    setVotes(newVotes);
    setVoted(optionId);
    localStorage.setItem(storageKey, optionId);
    localStorage.setItem(votesKey, JSON.stringify(newVotes));
  }

  const totalVotes = Object.values(votes).reduce((a, b) => a + b, 0);

  return (
    <div className="border border-rule-light bg-parchment-dark rounded-sm p-6 sm:p-8">
      <h2 className="font-display text-xl sm:text-2xl text-ink mb-6">
        {poll.question}
      </h2>

      <div className="space-y-3">
        {poll.options.map((opt) => {
          const count = votes[opt.id] || 0;
          const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;

          if (voted) {
            return (
              <div key={opt.id} className="relative">
                <div className="flex items-center justify-between py-3 px-4 relative z-10">
                  <div>
                    <span className="text-base text-ink">
                      {opt.label}
                      {voted === opt.id && (
                        <span className="ml-2 text-accent text-sm">
                          &#10003;
                        </span>
                      )}
                    </span>
                    <span className="block text-xs text-ink-muted mt-0.5">
                      {opt.description}
                    </span>
                  </div>
                  <span className="text-sm font-mono text-ink-muted ml-4 shrink-0">
                    {pct}%
                  </span>
                </div>
                <div
                  className="absolute inset-0 bg-accent-light rounded-sm transition-[width] duration-500 ease-out"
                  style={{ width: `${pct}%` }}
                />
              </div>
            );
          }

          return (
            <button
              key={opt.id}
              onClick={() => handleVote(opt.id)}
              className="w-full text-left py-3 px-4 border border-rule-light rounded-sm hover:border-accent hover:bg-accent-light transition-colors"
            >
              <span className="text-base text-ink">{opt.label}</span>
              <span className="block text-xs text-ink-muted mt-0.5">
                {opt.description}
              </span>
            </button>
          );
        })}
      </div>

      {voted && (
        <p className="mt-4 text-xs text-ink-muted">
          {totalVotes} vote{totalVotes !== 1 ? "s" : ""} total
        </p>
      )}
    </div>
  );
}
