import { Html, Head, Main, NextScript } from 'next/document';

/**
 * The document shell for every page, in both builds (the dashboard and the
 * marketing site).
 *
 * It exists for one attribute: `lang="en"` on `<html>`, so assistive
 * technology reads the page in the right language (WCAG 2.1 SC 3.1.1). Without
 * this file Next renders a bare `<html>`. Page titles and meta tags stay in
 * `_app.tsx` and `PageTitle`; nothing per-page belongs here.
 */
export default function Document() {
  return (
    <Html lang="en">
      <Head />
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
