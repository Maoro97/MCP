/** @type {import('next').NextConfig} */
export default {
  reactStrictMode: true,
  // ה-SSR רץ בתוך ה-VPC בישראל ולא ב-Edge: דפי תיק לקוח מרנדרים PII,
  // ואסור שהוא יעובד מחוץ לגבולות המדינה. ראה 04-tech-stack.md §2.1.
  output: 'standalone',
};
