import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "@/App";
import { StockDrawerProvider } from "@/lib/stockDrawer";
import { ThemeProvider } from "@/lib/theme";
import "@/index.css";

// Devtools are dev-only — lazy + env-gated so the package is dropped from the
// production bundle entirely.
const ReactQueryDevtools = import.meta.env.DEV
  ? lazy(() =>
      import("@tanstack/react-query-devtools").then((m) => ({ default: m.ReactQueryDevtools })),
    )
  : () => null;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      gcTime: 5 * 60_000,
      retry: 1,
      // Mobile tab-switching would otherwise refetch every mounted query at
      // once. Deliberate pollers set their own refetchInterval and are
      // unaffected.
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <StockDrawerProvider>
            <App />
          </StockDrawerProvider>
        </BrowserRouter>
      </ThemeProvider>
      <Suspense fallback={null}>
        <ReactQueryDevtools initialIsOpen={false} />
      </Suspense>
    </QueryClientProvider>
  </StrictMode>,
);
