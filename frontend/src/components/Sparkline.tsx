import { Area, AreaChart, ResponsiveContainer } from "recharts";

const TONE: Record<string, string> = {
  accent: "var(--color-accent)",
  pos: "var(--color-pos)",
  neg: "var(--color-neg)",
};

export function Sparkline({
  data,
  tone = "accent",
}: {
  data: number[];
  tone?: "accent" | "pos" | "neg";
}) {
  const rows = data.map((v, i) => ({ i, v }));
  const color = TONE[tone];
  const id = `spark-${tone}`;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={rows} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#${id})`}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
