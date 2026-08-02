import Link from 'next/link';

import { api } from '@/lib/api';
import { hebrewDate, money } from '@/lib/format';

export const dynamic = 'force-dynamic';

export default async function ClientsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const clients = await api.listClients(q);

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">לקוחות</h1>
          <p className="text-sm text-ink-muted">
            <span className="num">{clients.length}</span> לקוחות בסוכנות
          </p>
        </div>
        <form className="flex gap-2">
          <input
            type="search"
            name="q"
            defaultValue={q ?? ''}
            placeholder="חיפוש לפי שם או 4 ספרות ת״ז"
            className="w-64 rounded-lg border border-surface-line bg-surface px-3 py-1.5 text-sm
                       outline-none focus:border-brand"
          />
          <button className="rounded-lg bg-brand px-4 py-1.5 text-sm font-medium text-white">
            חפש
          </button>
        </form>
      </header>

      {clients.length === 0 ? (
        <p className="mt-8 rounded-xl border border-dashed border-surface-line bg-surface p-8 text-center text-ink-muted">
          {q ? 'לא נמצאו לקוחות התואמים לחיפוש' : 'אין עדיין לקוחות בסוכנות'}
        </p>
      ) : (
        <ul className="mt-5 divide-y divide-surface-line overflow-hidden rounded-xl border border-surface-line bg-surface">
          {clients.map((c) => (
            <li key={c.id}>
              <Link
                href={`/clients/${c.id}`}
                className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 hover:bg-surface-sunken"
              >
                <span className="min-w-40 font-medium">
                  {c.firstName} {c.lastName}
                </span>
                <span className="text-sm text-ink-muted">
                  ת.ז ...<bdi className="num">{c.nationalIdLast4}</bdi>
                </span>
                {c.age !== null && (
                  <span className="num text-sm text-ink-muted">גיל {c.age}</span>
                )}
                <span className="num text-sm text-ink-muted">
                  {c.productCount} מוצרים
                </span>
                <span className="num ms-auto font-semibold">{money(c.totalBalance)}</span>
                <span className="text-xs text-ink-faint">
                  עודכן {hebrewDate(c.lastIngestAt)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
