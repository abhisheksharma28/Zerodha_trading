import { createContext, useCallback, useContext, useMemo, useState } from "react";

interface Target {
  exchange: string;
  symbol: string;
}
interface Ctx {
  target: Target | null;
  open: (exchange: string, symbol: string) => void;
  close: () => void;
}

const StockDrawerCtx = createContext<Ctx | null>(null);

export function StockDrawerProvider({ children }: { children: React.ReactNode }) {
  const [target, setTarget] = useState<Target | null>(null);
  const open = useCallback((exchange: string, symbol: string) => {
    setTarget({ exchange: exchange.toUpperCase(), symbol: symbol.toUpperCase() });
  }, []);
  const close = useCallback(() => setTarget(null), []);
  const value = useMemo(() => ({ target, open, close }), [target, open, close]);
  return <StockDrawerCtx.Provider value={value}>{children}</StockDrawerCtx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- hook + provider co-located by design
export function useStockDrawer(): Ctx {
  const c = useContext(StockDrawerCtx);
  if (!c) throw new Error("useStockDrawer must be used within <StockDrawerProvider>");
  return c;
}
