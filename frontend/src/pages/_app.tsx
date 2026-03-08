import "@/styles/globals.css";
import type { AppProps } from "next/app";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AuthProvider } from "@/contexts/AuthContext";
import { WorkspaceProvider } from "@/contexts/WorkspaceContext";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { ToastContainer } from "@/components/ToastContainer";

export default function App({ Component, pageProps }: AppProps) {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <WorkspaceProvider>
          <NotificationProvider>
            <Component {...pageProps} />
            <ToastContainer />
          </NotificationProvider>
        </WorkspaceProvider>
      </AuthProvider>
    </ErrorBoundary>
  );
}
