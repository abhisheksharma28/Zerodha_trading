import { useEffect, useMemo, useRef, useState } from "react";

import type { VolumeProfile } from "@/api/orderflow";
import { countCompact } from "@/lib/format";
import { useTheme } from "@/lib/theme";

/** Canvas-rendered volume-at-price histogram: POC, value area (VAH/VAL),
 *  and HVN/LVN markers. One canvas, redrawn on data/size/theme change -
 *  no per-level DOM nodes. */
export function VolumeProfilePanel({
  profile,
  height = 380,
  lastPrice,
}: {
  profile: VolumeProfile;
  height?: number;
  lastPrice?: number | null;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const { theme } = useTheme();

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const maxVol = useMemo(
    () => Math.max(1, ...profile.levels.map((l) => l.volume)),
    [profile.levels],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || width === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const css = getComputedStyle(document.documentElement);
    const fg = css.getPropertyValue("--color-fg").trim() || "#e8e8e8";
    const faint = css.getPropertyValue("--color-fg-faint").trim() || "#888";
    const accent = css.getPropertyValue("--color-accent").trim() || "#e0b64d";
    const barColor = theme === "light" ? "rgba(60,110,200,0.55)" : "rgba(120,160,240,0.5)";
    const vaColor = theme === "light" ? "rgba(224,182,77,0.14)" : "rgba(224,182,77,0.12)";

    const levels = profile.levels;
    if (levels.length === 0) return;
    const padL = 8;
    const padR = 66; // room for the price labels
    const plotW = width - padL - padR;
    const rowH = height / levels.length;
    // levels come low->high; draw high at top
    const yFor = (i: number) => height - (i + 1) * rowH;

    // value-area band
    if (profile.vah_price != null && profile.val_price != null) {
      const iLo = levels.findIndex((l) => l.price >= profile.val_price!);
      let iHi = -1;
      for (let k = levels.length - 1; k >= 0; k--) {
        if (levels[k].price <= profile.vah_price!) { iHi = k; break; }
      }
      if (iLo >= 0 && iHi >= iLo) {
        const yTop = yFor(iHi);
        const yBot = yFor(iLo) + rowH;
        ctx.fillStyle = vaColor;
        ctx.fillRect(padL, yTop, plotW, yBot - yTop);
      }
    }

    ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textBaseline = "middle";

    for (let i = 0; i < levels.length; i++) {
      const lvl = levels[i];
      const y = yFor(i);
      const w = (lvl.volume / maxVol) * plotW;
      const isPoc = profile.poc_price != null && Math.abs(lvl.price - profile.poc_price) < 1e-9;
      const isHvn = profile.hvn_prices.some((p) => Math.abs(p - lvl.price) < 1e-9);
      const isLvn = profile.lvn_prices.some((p) => Math.abs(p - lvl.price) < 1e-9);

      ctx.fillStyle = isPoc ? accent : barColor;
      ctx.fillRect(padL, y + rowH * 0.12, Math.max(w, isLvn ? 1 : 0), rowH * 0.76);

      if (isHvn) {
        ctx.fillStyle = fg;
        ctx.fillRect(padL, y + rowH * 0.12, 2, rowH * 0.76);
      }

      // price label every Nth row (keep readable), always at POC/VAH/VAL
      const showLabel =
        levels.length <= 40 ||
        i % Math.ceil(levels.length / 32) === 0 ||
        isPoc;
      if (showLabel) {
        ctx.fillStyle = isPoc ? accent : faint;
        ctx.textAlign = "left";
        ctx.fillText(lvl.price.toFixed(2), width - padR + 4, y + rowH / 2);
      }
    }

    // POC volume callout
    if (profile.poc_price != null) {
      const pocLvl = levels.find((l) => Math.abs(l.price - profile.poc_price!) < 1e-9);
      if (pocLvl) {
        const y = yFor(levels.indexOf(pocLvl));
        ctx.fillStyle = accent;
        ctx.textAlign = "left";
        ctx.fillText(`POC ${countCompact(pocLvl.volume)}`, padL + 4, y + rowH / 2);
      }
    }

    // last price marker
    if (lastPrice != null) {
      let nearest = 0;
      for (let i = 1; i < levels.length; i++) {
        if (Math.abs(levels[i].price - lastPrice) < Math.abs(levels[nearest].price - lastPrice)) nearest = i;
      }
      const y = yFor(nearest) + rowH / 2;
      ctx.strokeStyle = fg;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(width - padR, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }, [profile, width, height, maxVol, theme, lastPrice]);

  return (
    <div ref={wrapRef} className="w-full">
      <canvas ref={canvasRef} style={{ width: "100%", height }} />
    </div>
  );
}
