/**
 * `_document.tsx` declares the page language on `<html>` (WCAG 2.1 SC 3.1.1).
 * Without the file Next renders a bare `<html>` and screen readers guess.
 *
 * The component is called as a function rather than rendered: `<Html>` needs
 * Next's server-side document context, which jsdom does not have, and the
 * returned element's props are the whole claim. The built HTML is checked by
 * grepping `out/index.html` after `npm run build:marketing`.
 */
import Document from '@/pages/_document';

// Required rather than imported: Next's lint rule allows a `next/document`
// import only in `pages/_document`, and this needs the same `Html` to compare.
const { Html } = jest.requireActual('next/document');

describe('_document', () => {
  it('renders <Html lang="en">', () => {
    const el = Document();
    expect(el.type).toBe(Html);
    expect(el.props.lang).toBe('en');
  });
});
