import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  deleteRegulation,
  listRegulations,
  RegulationListItem,
} from '../api';
import Layout from '../components/Layout';
import ConfirmDialog from '../components/ConfirmDialog';

function relativeTime(isoOrMs: string | number): string {
  const ms = typeof isoOrMs === 'number' ? isoOrMs : new Date(isoOrMs).getTime();
  if (!Number.isFinite(ms)) return '';
  const diff = Date.now() - ms;
  if (diff < 60_000) return 'just now';
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const CAT_BADGE: Record<string, string> = {
  regulations: 'bg-blue-100 text-blue-800',
  notices: 'bg-red-100 text-red-800',
  guidance: 'bg-emerald-100 text-emerald-800',
};

export default function AdminHome() {
  const navigate = useNavigate();
  const [items, setItems] = useState<RegulationListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RegulationListItem | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setItems(await listRegulations());
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load');
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function confirmDelete() {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await deleteRegulation(deleteTarget.slug);
      setDeleteTarget(null);
      await refresh();
    } catch (err: any) {
      setError(err.message || 'Delete failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Layout>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Regulations</h1>
        <button
          onClick={() => navigate('/new')}
          className="px-4 py-2 bg-[#003366] text-white text-sm font-semibold rounded hover:bg-[#002244]"
        >
          + New Regulation
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded mb-4 text-sm">
          {error}
        </div>
      )}

      {items === null ? (
        <p className="text-slate-500">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-slate-500 italic">
          No regulations yet. Click "+ New Regulation" to create one.
        </p>
      ) : (
        <div className="bg-white rounded shadow border border-slate-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left">
              <tr>
                <th className="px-4 py-3 font-semibold">Title</th>
                <th className="px-4 py-3 font-semibold">Category</th>
                <th className="px-4 py-3 font-semibold">Effective</th>
                <th className="px-4 py-3 font-semibold">Updated</th>
                <th className="px-4 py-3 font-semibold">PDF</th>
                <th className="px-4 py-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={`${r.category}/${r.slug}`} className="border-t border-slate-200">
                  <td className="px-4 py-3">
                    <div className="font-semibold">{r.title}</div>
                    <div className="text-xs text-slate-500 font-mono">{r.slug}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block px-2 py-0.5 text-xs font-semibold rounded ${CAT_BADGE[r.category] || 'bg-slate-100 text-slate-800'}`}
                    >
                      {r.category}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{r.effective_date || '—'}</td>
                  <td className="px-4 py-3 text-slate-600">{relativeTime(r.mtime || r.updated_at)}</td>
                  <td className="px-4 py-3">{r.has_pdf ? '📄' : ''}</td>
                  <td className="px-4 py-3 text-right space-x-2">
                    <Link
                      to={`/edit/${r.slug}`}
                      className="px-3 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded"
                    >
                      Edit
                    </Link>
                    <a
                      href={`/${r.category}/${r.slug}.html`}
                      target="_blank"
                      rel="noreferrer"
                      className="px-3 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded"
                    >
                      View
                    </a>
                    <button
                      onClick={() => setDeleteTarget(r)}
                      className="px-3 py-1 bg-red-50 hover:bg-red-100 text-red-700 text-xs font-semibold rounded"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete regulation?"
        message={
          deleteTarget
            ? `This will permanently remove "${deleteTarget.title}" and its generated HTML${deleteTarget.has_pdf ? ' and PDF' : ''}.`
            : ''
        }
        confirmLabel={busy ? 'Deleting…' : 'Delete'}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </Layout>
  );
}
