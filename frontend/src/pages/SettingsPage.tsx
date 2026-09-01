import { useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useTheme, type Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const TABS = ["General", "Broker", "Risk Management", "Notifications", "API"] as const;
const PREFS_KEY = "ui-prefs";

interface Prefs {
  currency: string;
  timezone: string;
  dateFormat: string;
  numberFormat: string;
}
const DEFAULT_PREFS: Prefs = {
  currency: "INR",
  timezone: "Asia/Kolkata",
  dateFormat: "DD/MM/YYYY",
  numberFormat: "1,23,456.78",
};

function loadPrefs(): Prefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

const selectCls =
  "h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

export default function SettingsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("General");
  const { theme, setTheme } = useTheme();
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [saved, setSaved] = useState(false);

  const update = (patch: Partial<Prefs>) => {
    setPrefs((p) => ({ ...p, ...patch }));
    setSaved(false);
  };
  const pickTheme = (t: Theme) => {
    setTheme(t);
    setSaved(false);
  };

  function save() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
      setSaved(true);
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Settings" subtitle="Account, display, broker and risk preferences." />

      <div className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              "rounded-t-md px-3 py-2 text-xs font-medium",
              t === tab
                ? "border-b-2 border-accent text-fg"
                : "text-fg-muted hover:text-fg",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "General" && (
        <SectionCard title="General">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label>Theme</Label>
              <div className="inline-flex rounded-md border border-line-strong bg-surface p-0.5">
                {(["dark", "light"] as Theme[]).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => pickTheme(t)}
                    className={cn(
                      "rounded px-3 py-1 text-xs font-medium capitalize",
                      theme === t ? "bg-accent-soft text-accent" : "text-fg-muted hover:text-fg",
                    )}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <Field label="Account currency">
              <select
                className={selectCls}
                value={prefs.currency}
                onChange={(e) => update({ currency: e.target.value })}
              >
                <option>INR</option>
                <option>USD</option>
              </select>
            </Field>
            <Field label="Time zone">
              <select
                className={selectCls}
                value={prefs.timezone}
                onChange={(e) => update({ timezone: e.target.value })}
              >
                <option>Asia/Kolkata</option>
                <option>UTC</option>
              </select>
            </Field>
            <Field label="Date format">
              <select
                className={selectCls}
                value={prefs.dateFormat}
                onChange={(e) => update({ dateFormat: e.target.value })}
              >
                <option>DD/MM/YYYY</option>
                <option>MM/DD/YYYY</option>
                <option>YYYY-MM-DD</option>
              </select>
            </Field>
            <Field label="Number format">
              <select
                className={selectCls}
                value={prefs.numberFormat}
                onChange={(e) => update({ numberFormat: e.target.value })}
              >
                <option>1,23,456.78</option>
                <option>123,456.78</option>
              </select>
            </Field>
          </div>
          <div className="mt-5 flex items-center gap-3">
            <Button size="sm" onClick={save}>
              Save settings
            </Button>
            {saved && <span className="text-xs text-pos">Saved</span>}
          </div>
        </SectionCard>
      )}

      {tab === "Broker" && (
        <SectionCard title="Broker">
          <p className="text-sm text-fg-muted">
            Zerodha Kite Connect is the broker for this platform.{" "}
            <Link to="/broker" className="text-accent hover:underline">
              Manage the connection →
            </Link>
          </p>
        </SectionCard>
      )}

      {tab === "Risk Management" && (
        <SectionCard title="Risk Management">
          <p className="text-sm text-fg-muted">
            Global risk limits (max daily loss, max open positions, per-strategy exposure caps) are
            enforced by the backend risk engine. A UI to edit them lands with the live-trading
            hardening phase.
          </p>
        </SectionCard>
      )}

      {tab === "Notifications" && (
        <SectionCard title="Notifications">
          <p className="text-sm text-fg-muted">
            Email / webhook delivery for alerts and fills is configured here once the live-data
            phase ships.
          </p>
        </SectionCard>
      )}

      {tab === "API" && (
        <SectionCard title="API">
          <p className="text-sm text-fg-muted">
            The platform exposes a REST API under <code className="text-fg">/api/v1</code>. Token
            management for external clients is a later addition.
          </p>
        </SectionCard>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
