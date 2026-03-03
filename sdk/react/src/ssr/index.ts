/**
 * SSR utilities for the Experimentation Platform React SDK.
 *
 * Use these utilities in server-side rendering contexts (Next.js getServerSideProps,
 * Remix loaders, etc.) where browser APIs are not available.
 *
 * @example
 * import { ServerClient } from '@experimentation-platform/react-sdk/ssr';
 *
 * export async function getServerSideProps({ req }) {
 *   const client = new ServerClient({ apiKey: process.env.API_KEY, baseUrl: process.env.API_URL });
 *   const flags = await client.getAll(['new-checkout', 'redesign'], { userId: req.session.userId });
 *   return { props: { flags } };
 * }
 */
export { ServerClient } from '../client/ServerClient';
