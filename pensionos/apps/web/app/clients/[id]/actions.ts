'use server';

import { revalidatePath } from 'next/cache';

import { api } from '@/lib/api';

const STATUS_HE: Record<string, string> = {
  succeeded: 'הקובץ פוענח במלואו',
  partial: 'הקובץ פוענח חלקית',
  no_data: 'היצרן דיווח שאין מידע עבור הלקוח',
  failed: 'הקובץ לא ניתן לפענוח',
  quarantined: 'הקובץ הועבר להסגר ולא נקלט',
};

export async function ingestAction(formData: FormData) {
  const clientId = String(formData.get('clientId'));
  const file = formData.get('file');

  if (!(file instanceof File) || file.size === 0) {
    return { ok: false as const, message: 'לא נבחר קובץ' };
  }

  try {
    const r = await api.ingest(clientId, file);
    revalidatePath(`/clients/${clientId}`);

    const details: string[] = [];
    if (r.duplicate) {
      details.push('קובץ זהה כבר נקלט בעבר — לא בוצעה קליטה כפולה');
    } else {
      details.push(`${r.productsPersisted} מוצרים נקלטו`);
      if (r.staleSkipped > 0) {
        details.push(
          `${r.staleSkipped} מוצרים לא עודכנו — הדיווח הקיים עדכני או שלם יותר`,
        );
      }
    }
    for (const issue of r.blockingIssues.slice(0, 5)) details.push(issue);

    return {
      ok: true as const,
      headline: STATUS_HE[r.status] ?? r.status,
      details,
    };
  } catch (err) {
    return { ok: false as const, message: (err as Error).message };
  }
}
