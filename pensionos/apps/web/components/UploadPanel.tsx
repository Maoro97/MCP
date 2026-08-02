'use client';

import { useRef, useState, useTransition } from 'react';

import type { ingestAction } from '@/app/clients/[id]/actions';

type Result = Awaited<ReturnType<typeof ingestAction>>;

/**
 * קליטת קובץ מסלקה ידנית.
 *
 * זמני עד שאינטגרציית המסלקה (E3) תיבנה — ואז יישאר ככלי לקבצים שהלקוח
 * מביא בעצמו. התוצאה מוצגת במלואה, כולל מה **לא** נקלט ולמה: קליטה
 * שקטה שמחזירה "בוצע" בלי לפרט היא בדיוק מה שגורם לסוכן לגלות חוסרים
 * רק כשהוא כבר מול הלקוח.
 */
export function UploadPanel({
  clientId,
  action,
}: {
  clientId: string;
  action: (formData: FormData) => Promise<Result>;
}) {
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<Result | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function submit(formData: FormData) {
    startTransition(async () => {
      setResult(await action(formData));
      if (inputRef.current) inputRef.current.value = '';
    });
  }

  return (
    <section className="rounded-xl border border-surface-line bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">קליטת קובץ מסלקה</h2>
      <form action={submit} className="mt-3 flex flex-wrap items-center gap-3">
        <input type="hidden" name="clientId" value={clientId} />
        <input
          ref={inputRef}
          type="file"
          name="file"
          accept=".xml,text/xml,application/xml"
          required
          className="block text-sm text-ink-muted file:me-3 file:rounded-lg file:border-0
                     file:bg-brand-soft file:px-3 file:py-1.5 file:text-sm
                     file:font-medium file:text-brand hover:file:bg-brand-soft/70"
        />
        <button
          type="submit"
          disabled={pending}
          className="rounded-lg bg-brand px-4 py-1.5 text-sm font-medium text-white
                     disabled:opacity-50"
        >
          {pending ? 'מפענח…' : 'קלוט קובץ'}
        </button>
      </form>

      {result && (
        <div
          className={[
            'mt-3 rounded-lg px-3 py-2 text-sm',
            result.ok ? 'bg-surface-sunken' : 'bg-risk-high/10 text-risk-high',
          ].join(' ')}
        >
          {!result.ok ? (
            <p>{result.message}</p>
          ) : (
            <>
              <p className="font-medium">{result.headline}</p>
              {result.details.length > 0 && (
                <ul className="mt-1 space-y-0.5 text-ink-muted">
                  {result.details.map((d, i) => (
                    <li key={i}>· {d}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
