import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Category,
  createRegulation,
  getRegulation,
  Regulation,
  updateRegulation,
} from '../api';
import Layout from '../components/Layout';
import SectionEditor from '../components/SectionEditor';

interface Props {
  mode: 'create' | 'edit';
}

const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,80}$/;

function emptyDraft(): Regulation {
  return {
    slug: '',
    category: 'regulations',
    title: '',
    subtitle: '',
    effective_date: '',
    reference_number: '',
    summary: '',
    sections: [],
    updated_at: '',
  };
}

export default function Editor({ mode }: Props) {
  const { slug: slugParam } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<Regulation | null>(
    mode === 'create' ? emptyDraft() : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [generatesPdf, setGeneratesPdf] = useState(false);

  useEffect(() => {
    if (mode === 'edit' && slugParam) {
      getRegulation(slugParam)
        .then((r) => {
          setDraft(r);
          setGeneratesPdf(!!r.pdf?.enabled);
        })
        .catch((err) => setError(err.message || 'Failed to load'));
    }
  }, [mode, slugParam]);

  function update<K extends keyof Regulation>(key: K, value: Regulation[K]) {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  }

  async function save() {
    if (!draft) return;
    setError(null);

    if (!draft.title.trim()) return setError('Title is required');
    if (mode === 'create' && !SLUG_RE.test(draft.slug)) {
      return setError('Slug must be lowercase letters, digits, hyphens (2–80 chars)');
    }

    const payload: Regulation = { ...draft };
    if (generatesPdf) {
      payload.pdf = {
        enabled: true,
        filename: payload.pdf?.filename || `${draft.slug}.pdf`,
        document_title: payload.pdf?.document_title,
      };
    } else {
      delete payload.pdf;
    }

    setSaving(true);
    try {
      if (mode === 'create') {
        await createRegulation(payload);
      } else if (slugParam) {
        await updateRegulation(slugParam, payload);
      }
      navigate('/');
    } catch (err: any) {
      setError(err.message || 'Save failed');
      setSaving(false);
    }
  }

  if (!draft) {
    return (
      <Layout>
        {error ? (
          <p className="text-red-700">{error}</p>
        ) : (
          <p className="text-slate-500">Loading…</p>
        )}
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">
          {mode === 'create' ? 'New Regulation' : `Edit: ${draft.title}`}
        </h1>
        <div className="space-x-2">
          <button
            onClick={() => navigate('/')}
            className="px-4 py-2 text-sm font-semibold bg-slate-100 hover:bg-slate-200 rounded"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="px-4 py-2 text-sm font-semibold bg-[#003366] text-white hover:bg-[#002244] rounded disabled:opacity-60"
          >
            {saving ? 'Saving…' : 'Save & Regenerate'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded mb-4 text-sm">
          {error}
        </div>
      )}

      <div className="bg-white rounded shadow border border-slate-200 p-6 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Slug">
            <input
              value={draft.slug}
              onChange={(e) => update('slug', e.target.value.toLowerCase())}
              disabled={mode === 'edit'}
              placeholder="e.g. tariff-schedule-2026"
              className="w-full text-sm border border-slate-300 rounded px-2 py-1 font-mono disabled:bg-slate-100"
            />
            {mode === 'edit' && (
              <p className="text-xs text-slate-500 mt-1">
                Slug is locked after creation.
              </p>
            )}
          </Field>
          <Field label="Category">
            <select
              value={draft.category}
              onChange={(e) => update('category', e.target.value as Category)}
              disabled={mode === 'edit'}
              className="w-full text-sm border border-slate-300 rounded px-2 py-1 disabled:bg-slate-100"
            >
              <option value="regulations">regulations</option>
              <option value="notices">notices</option>
              <option value="guidance">guidance</option>
            </select>
          </Field>
        </div>

        <Field label="Title">
          <input
            value={draft.title}
            onChange={(e) => update('title', e.target.value)}
            className="w-full text-sm border border-slate-300 rounded px-2 py-1"
          />
        </Field>

        <Field label="Subtitle">
          <input
            value={draft.subtitle || ''}
            onChange={(e) => update('subtitle', e.target.value)}
            className="w-full text-sm border border-slate-300 rounded px-2 py-1"
            placeholder="e.g. CFR Title 19, Chapter IV"
          />
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Effective Date">
            <input
              type="date"
              value={draft.effective_date || ''}
              onChange={(e) => update('effective_date', e.target.value)}
              className="w-full text-sm border border-slate-300 rounded px-2 py-1"
            />
          </Field>
          <Field label="Reference Number">
            <input
              value={draft.reference_number || ''}
              onChange={(e) => update('reference_number', e.target.value)}
              className="w-full text-sm border border-slate-300 rounded px-2 py-1"
              placeholder="e.g. ATCA/TS/2026/001"
            />
          </Field>
        </div>

        <Field label="Summary">
          <textarea
            value={draft.summary}
            onChange={(e) => update('summary', e.target.value)}
            rows={3}
            className="w-full text-sm border border-slate-300 rounded px-2 py-1"
          />
        </Field>

        <Field label="Generate PDF">
          <label className="text-sm">
            <input
              type="checkbox"
              checked={generatesPdf}
              onChange={(e) => setGeneratesPdf(e.target.checked)}
              className="mr-2"
            />
            Also generate a PDF document for this regulation
          </label>
        </Field>
      </div>

      <div className="mt-6 bg-white rounded shadow border border-slate-200 p-6">
        <h2 className="text-lg font-bold mb-4">Sections</h2>
        <SectionEditor
          sections={draft.sections}
          onChange={(s) => update('sections', s)}
        />
      </div>
    </Layout>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs uppercase tracking-wider font-bold text-slate-500 mb-1">
        {label}
      </label>
      {children}
    </div>
  );
}
