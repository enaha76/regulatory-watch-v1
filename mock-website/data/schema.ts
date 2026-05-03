// JSON schema for editable regulations. Both the HTML and PDF generators consume
// instances of this type so the admin UI has a single source of truth.

export type SectionType =
  | 'heading'
  | 'paragraph'
  | 'list'
  | 'table'
  | 'note';

export type Section =
  | { type: 'heading'; level: 1 | 2 | 3; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'table'; columns: string[]; rows: string[][] }
  | { type: 'note'; style: 'critical' | 'info' | 'warning'; title?: string; text: string };

export interface RegulationDoc {
  slug: string;
  category: 'regulations' | 'notices' | 'guidance';
  title: string;
  subtitle?: string;
  effective_date?: string;
  reference_number?: string;
  summary: string;
  sections: Section[];
  pdf?: {
    enabled: boolean;
    filename: string;
    document_title?: string;
  };
  updated_at: string;
}
