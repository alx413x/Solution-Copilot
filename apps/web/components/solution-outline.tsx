"use client";
import { useState } from "react";
import type { components } from "../../../packages/contracts/api";

type Entry = components["schemas"]["OutlineEntry"];
type Section = components["schemas"]["SectionView"];
export function SolutionOutline({
  sections,
  disabled,
  approve,
}: {
  sections: Section[];
  disabled: boolean;
  approve: (sections: Entry[]) => Promise<void>;
}) {
  const [entries, setEntries] = useState<Entry[]>(
    sections.map(({ id, title, goal }) => ({ id, title, goal })),
  );
  function move(index: number, delta: number) {
    const next = [...entries];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    setEntries(next);
  }
  return (
    <section className="panel outline-editor">
      <h2>确认方案大纲</h2>
      <p className="muted">
        可生成定制大纲，也可调整当前模板。重新生成大纲会替换尚未确认的调整；确认后按此顺序逐章生成。
      </p>
      <form
        className="record-form"
        onSubmit={(e) => {
          e.preventDefault();
          void approve(entries);
        }}
      >
        {entries.map((entry, i) => (
          <fieldset key={entry.id} disabled={disabled}>
            <legend>第 {i + 1} 章</legend>
            <label>
              章节标题
              <input
                required
                maxLength={160}
                value={entry.title}
                onChange={(e) =>
                  setEntries(
                    entries.map((s) =>
                      s.id === entry.id ? { ...s, title: e.target.value } : s,
                    ),
                  )
                }
              />
            </label>
            <label>
              章节目标
              <textarea
                maxLength={3000}
                value={entry.goal ?? ""}
                onChange={(e) =>
                  setEntries(
                    entries.map((s) =>
                      s.id === entry.id ? { ...s, goal: e.target.value } : s,
                    ),
                  )
                }
              />
            </label>
            <div className="actions">
              <button
                type="button"
                disabled={i === 0}
                aria-label={`上移第 ${i + 1} 章`}
                onClick={() => move(i, -1)}
              >
                上移
              </button>
              <button
                type="button"
                disabled={i === entries.length - 1}
                aria-label={`下移第 ${i + 1} 章`}
                onClick={() => move(i, 1)}
              >
                下移
              </button>
              <button
                type="button"
                disabled={entries.length === 1}
                aria-label={`删除第 ${i + 1} 章`}
                onClick={() =>
                  setEntries(entries.filter((s) => s.id !== entry.id))
                }
              >
                删除
              </button>
            </div>
            {sections
              .find((s) => s.id === entry.id)
              ?.citations.map((c) => (
                <details key={c.id}>
                  <summary>大纲来源：{c.title}</summary>
                  <blockquote>{c.quote}</blockquote>
                  <p className="muted">引用待核实</p>
                </details>
              ))}
          </fieldset>
        ))}
        <div className="actions">
          <button
            type="button"
            disabled={disabled || entries.length >= 20}
            onClick={() =>
              setEntries([
                ...entries,
                { id: crypto.randomUUID(), title: "新增章节", goal: "" },
              ])
            }
          >
            增加章节
          </button>
          <button className="primary" disabled={disabled}>
            确认大纲并生成正文
          </button>
        </div>
      </form>
    </section>
  );
}
