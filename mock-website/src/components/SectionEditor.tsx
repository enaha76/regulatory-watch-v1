import { Section } from '../api';

interface Props {
  sections: Section[];
  onChange: (next: Section[]) => void;
}

const blank: Record<Section['type'], () => Section> = {
  heading: () => ({ type: 'heading', level: 2, text: 'New heading' }),
  paragraph: () => ({ type: 'paragraph', text: '' }),
  list: () => ({ type: 'list', ordered: false, items: [''] }),
  table: () => ({ type: 'table', columns: ['Column 1', 'Column 2'], rows: [['', '']] }),
  note: () => ({ type: 'note', style: 'info', title: '', text: '' }),
};

export default function SectionEditor({ sections, onChange }: Props) {
  function update(i: number, patch: Partial<Section>) {
    const next = sections.slice();
    next[i] = { ...next[i], ...patch } as Section;
    onChange(next);
  }
  function remove(i: number) {
    onChange(sections.filter((_, j) => j !== i));
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= sections.length) return;
    const next = sections.slice();
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  }
  function add(type: Section['type']) {
    onChange([...sections, blank[type]()]);
  }

  return (
    <div className="space-y-4">
      {sections.map((s, i) => (
        <div
          key={i}
          className="border border-slate-200 rounded p-4 bg-slate-50"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs uppercase tracking-wider font-bold text-slate-500">
              {s.type}
            </div>
            <div className="space-x-1">
              <button
                type="button"
                onClick={() => move(i, -1)}
                disabled={i === 0}
                className="px-2 py-1 text-xs bg-white border border-slate-300 rounded disabled:opacity-30"
              >
                ↑
              </button>
              <button
                type="button"
                onClick={() => move(i, 1)}
                disabled={i === sections.length - 1}
                className="px-2 py-1 text-xs bg-white border border-slate-300 rounded disabled:opacity-30"
              >
                ↓
              </button>
              <button
                type="button"
                onClick={() => remove(i)}
                className="px-2 py-1 text-xs bg-red-50 border border-red-200 text-red-700 rounded"
              >
                Remove
              </button>
            </div>
          </div>

          {s.type === 'heading' && (
            <div className="flex items-center gap-2">
              <select
                value={s.level}
                onChange={(e) => update(i, { level: Number(e.target.value) as 1 | 2 | 3 })}
                className="text-sm border border-slate-300 rounded px-2 py-1"
              >
                <option value={1}>H1</option>
                <option value={2}>H2</option>
                <option value={3}>H3</option>
              </select>
              <input
                value={s.text}
                onChange={(e) => update(i, { text: e.target.value })}
                className="flex-1 text-sm border border-slate-300 rounded px-2 py-1"
              />
            </div>
          )}

          {s.type === 'paragraph' && (
            <textarea
              value={s.text}
              onChange={(e) => update(i, { text: e.target.value })}
              rows={4}
              className="w-full text-sm border border-slate-300 rounded px-2 py-1"
            />
          )}

          {s.type === 'list' && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <label className="text-sm">
                  <input
                    type="checkbox"
                    checked={s.ordered}
                    onChange={(e) => update(i, { ordered: e.target.checked })}
                    className="mr-1"
                  />
                  Ordered (numbered)
                </label>
              </div>
              {s.items.map((item, k) => (
                <div key={k} className="flex gap-2 mb-1">
                  <input
                    value={item}
                    onChange={(e) => {
                      const items = s.items.slice();
                      items[k] = e.target.value;
                      update(i, { items });
                    }}
                    className="flex-1 text-sm border border-slate-300 rounded px-2 py-1"
                    placeholder="List item"
                  />
                  <button
                    type="button"
                    onClick={() => update(i, { items: s.items.filter((_, j) => j !== k) })}
                    className="px-2 py-1 text-xs bg-red-50 border border-red-200 text-red-700 rounded"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => update(i, { items: [...s.items, ''] })}
                className="text-xs px-2 py-1 bg-white border border-slate-300 rounded mt-1"
              >
                + Add item
              </button>
            </div>
          )}

          {s.type === 'table' && (
            <div className="space-y-2">
              <div className="text-xs text-slate-600">Columns:</div>
              <div className="flex gap-1 flex-wrap">
                {s.columns.map((col, k) => (
                  <input
                    key={k}
                    value={col}
                    onChange={(e) => {
                      const cols = s.columns.slice();
                      cols[k] = e.target.value;
                      update(i, { columns: cols });
                    }}
                    className="text-xs border border-slate-300 rounded px-1 py-0.5 w-32"
                  />
                ))}
                <button
                  type="button"
                  onClick={() =>
                    update(i, {
                      columns: [...s.columns, ''],
                      rows: s.rows.map((r) => [...r, '']),
                    })
                  }
                  className="text-xs px-2 py-0.5 bg-white border border-slate-300 rounded"
                >
                  + col
                </button>
              </div>
              <div className="text-xs text-slate-600 mt-2">Rows:</div>
              {s.rows.map((row, ri) => (
                <div key={ri} className="flex gap-1">
                  {row.map((cell, ci) => (
                    <input
                      key={ci}
                      value={cell}
                      onChange={(e) => {
                        const rows = s.rows.map((r, j) =>
                          j === ri ? r.map((c, m) => (m === ci ? e.target.value : c)) : r,
                        );
                        update(i, { rows });
                      }}
                      className="text-xs border border-slate-300 rounded px-1 py-0.5 w-32"
                    />
                  ))}
                  <button
                    type="button"
                    onClick={() => update(i, { rows: s.rows.filter((_, j) => j !== ri) })}
                    className="text-xs px-2 py-0.5 bg-red-50 border border-red-200 text-red-700 rounded"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() =>
                  update(i, { rows: [...s.rows, s.columns.map(() => '')] })
                }
                className="text-xs px-2 py-1 bg-white border border-slate-300 rounded"
              >
                + row
              </button>
            </div>
          )}

          {s.type === 'note' && (
            <div className="space-y-2">
              <select
                value={s.style}
                onChange={(e) =>
                  update(i, { style: e.target.value as 'critical' | 'info' | 'warning' })
                }
                className="text-sm border border-slate-300 rounded px-2 py-1"
              >
                <option value="info">Info (blue)</option>
                <option value="warning">Warning (amber)</option>
                <option value="critical">Critical (red)</option>
              </select>
              <input
                value={s.title || ''}
                placeholder="Note title (optional)"
                onChange={(e) => update(i, { title: e.target.value })}
                className="w-full text-sm border border-slate-300 rounded px-2 py-1"
              />
              <textarea
                value={s.text}
                onChange={(e) => update(i, { text: e.target.value })}
                rows={3}
                className="w-full text-sm border border-slate-300 rounded px-2 py-1"
              />
            </div>
          )}
        </div>
      ))}

      <div className="flex gap-2 flex-wrap">
        {(['heading', 'paragraph', 'list', 'table', 'note'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => add(t)}
            className="px-3 py-1 text-xs bg-white border border-slate-300 rounded hover:bg-slate-50"
          >
            + {t}
          </button>
        ))}
      </div>
    </div>
  );
}
