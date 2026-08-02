import type { FieldSource } from '@/lib/api';
import { MISSING } from '@/lib/format';

/**
 * ערך + מקורו.
 *
 * דרישת ציות ולא קישוט: הסוכן חייב לדעת אם המספר הגיע מהמסלקה או הוזן
 * ידנית, ממי, לאיזה תאריך, ומה היה הערך הגולמי לפני הנרמול. בביקורת זו
 * בדיוק השאלה — "על סמך מה כתבת 0.35% במסמך ההנמקה?".
 *
 * ערך שנוצר מהיוריסטיקה (confidence < 1) מסומן ויזואלית, כדי שלא ייראה
 * ודאי כמו ערך שדווח במפורש.
 */
export function ValueWithSource({
  value,
  source,
  className = '',
}: {
  value: string;
  source?: FieldSource;
  className?: string;
}) {
  const missing = value === MISSING;
  const uncertain = source !== undefined && source.confidence < 1;

  const tooltip = source
    ? [
        `מקור: ${source.origin === 'manual' ? 'הוזן ידנית' : 'מסלקה'}`,
        source.providerName ? `יצרן: ${source.providerName}` : null,
        source.reportDate ? `נכון ל: ${source.reportDate}` : null,
        source.raw !== null ? `ערך גולמי: ${source.raw}` : null,
        uncertain ? `רמת ביטחון: ${Math.round(source.confidence * 100)}%` : null,
        source.fixes.length ? `תיקונים: ${source.fixes.join(', ')}` : null,
      ]
        .filter(Boolean)
        .join('\n')
    : undefined;

  return (
    <span
      title={tooltip}
      className={[
        'num',
        missing ? 'text-ink-faint italic' : 'text-ink',
        uncertain ? 'underline decoration-dotted decoration-risk-med underline-offset-4' : '',
        source && !missing ? 'cursor-help' : '',
        className,
      ].join(' ')}
    >
      {value}
      {uncertain && <span className="ms-1 text-risk-med not-italic">≈</span>}
    </span>
  );
}
