import type { Metadata } from 'next';

import './globals.css';

export const metadata: Metadata = {
  title: 'PensionOS · תיק לקוח',
  description: 'מערכת לסוכני ביטוח ופנסיה',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // dir="rtl" ברמת ה-html, לא ברמת קומפוננטה: כך כל Logical Property
  // (ms-/me-/start/end) מתנהג נכון בלי טיפול פרטני בכל מקום.
  return (
    <html lang="he" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
