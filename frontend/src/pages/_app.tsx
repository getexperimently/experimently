import "@/styles/globals.css";
import type { AppProps } from "next/app";
import Head from "next/head";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AuthProvider } from "@/contexts/AuthContext";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { ToastContainer } from "@/components/ToastContainer";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { routeKind } from "@/utils/routes";

export default function App({ Component, pageProps, router }: AppProps) {
  const kind = routeKind(router.pathname);

  let page = <Component {...pageProps} />;
  if (kind === "protected") {
    page = <RequireAuth>{page}</RequireAuth>;
  }
  if (kind !== "bare") {
    page = <AppShell>{page}</AppShell>;
  }

  return (
    <ErrorBoundary>
      <Head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
        <title>Experimently</title>
      </Head>
      <AuthProvider>
        <NotificationProvider>
          {page}
          <ToastContainer />
        </NotificationProvider>
      </AuthProvider>
    </ErrorBoundary>
  );
}
